"""
Core pulling agent implementation.
"""
import asyncio
import signal
from pathlib import Path
from datetime import datetime
from typing import Optional
import logging

from .config import AgentConfig, AgentState
from .mongo_client import MongoClientManager
from .trigger_worker import TriggerWorker
from .distributed_control import DistributedControlCoordinator

logger = logging.getLogger(__name__)


class PullingAgent:
    """
    Background agent that continuously pulls data from MongoDB.
    
    Features:
    - Graceful shutdown on SIGTERM/SIGINT
    - Pause/resume via signals (SIGUSR1/SIGUSR2)
    - File-based health checks for Kubernetes
    - Heartbeat monitoring
    - Configurable polling interval
    """
    
    def __init__(self, config: AgentConfig, mongo_manager: MongoClientManager):
        self.config = config
        self.mongo = mongo_manager
        self.state = AgentState.RUNNING

        # Worker for processing documents
        self.worker = TriggerWorker(config, mongo_manager)

        # Event coordination
        self._shutdown_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Start unpaused

        # Health check files
        self.health_dir = Path("/tmp/health")
        self.health_dir.mkdir(exist_ok=True)
        self.liveness_file = self.health_dir / "liveness"
        self.readiness_file = self.health_dir / "readiness"

        # Control file
        self.control_file = Path("/tmp/control/state")

        # Distributed control (optional, based on config)
        self.distributed_control: Optional[DistributedControlCoordinator] = None
        if config.enable_distributed_control:
            self.distributed_control = DistributedControlCoordinator(
                mongo_client=mongo_manager.client,
                db_name=config.mongodb_database,
                polling_interval=config.control_polling_interval,
                enable_change_streams=config.enable_change_streams
            )

        # Background tasks
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._control_monitor_task: Optional[asyncio.Task] = None
        self._distributed_watch_task: Optional[asyncio.Task] = None

        # Statistics
        self._last_heartbeat = datetime.now()
        self._errors_count = 0

        # Setup signal handlers
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self) -> None:
        """Setup Unix signal handlers for graceful shutdown and control"""
        loop = asyncio.get_event_loop()

        # SIGTERM: Graceful shutdown (K8s sends this)
        loop.add_signal_handler(
            signal.SIGTERM,
            lambda: asyncio.create_task(self.shutdown())
        )

        # SIGINT: Graceful shutdown (Ctrl+C)
        loop.add_signal_handler(
            signal.SIGINT,
            lambda: asyncio.create_task(self.shutdown())
        )

        # SIGUSR1: Pause
        loop.add_signal_handler(
            signal.SIGUSR1,
            lambda: self.pause()
        )

        # SIGUSR2: Resume
        loop.add_signal_handler(
            signal.SIGUSR2,
            lambda: self.resume()
        )

    async def _on_distributed_control_command(self, command: str, document: dict) -> None:
        """
        Callback executed when global control command changes.
        Called by MongoDB Change Stream or polling mechanism.
        """
        logger.info(
            f"[Worker Control] Processing global command: {command} "
            f"(version {document['version']}, reason: {document.get('reason', 'N/A')})"
        )

        if command == "pause":
            self.pause()
        elif command == "running":  # "resume" is represented as "running"
            self.resume()
        elif command == "shutdown":
            await self.shutdown()
        else:
            logger.warning(f"[Worker Control] Unknown command received: {command}")

    async def _sync_initial_distributed_state(self) -> None:
        """
        On startup, sync agent state with current global command.
        This handles the case where the agent starts when command is already "pause".
        """
        if not self.distributed_control:
            return

        current = await self.distributed_control.get_current_command()
        if current:
            command = current["command"]
            logger.info(
                f"[Worker Control] Initial global state: {command} "
                f"(version {current['version']})"
            )

            # Apply initial state
            if command == "pause" and self.state == AgentState.RUNNING:
                logger.info("[Worker Control] Syncing to paused state on startup")
                self.pause()
            elif command == "running" and self.state == AgentState.PAUSED:
                logger.info("[Worker Control] Syncing to running state on startup")
                self.resume()
    
    async def run(self) -> None:
        """Main event loop"""
        logger.info("Starting pulling agent")
        logger.info(f"Configuration: poll_interval={self.config.poll_interval}s, "
                   f"batch_size={self.config.batch_size}")

        # Connect to MongoDB
        await self.mongo.connect()

        # Initialize distributed control if enabled
        if self.distributed_control:
            logger.info("[Worker Control] Initializing cluster coordination")
            await self.distributed_control.initialize()
            await self._sync_initial_distributed_state()

            # Start watching for distributed control changes
            self._distributed_watch_task = self.distributed_control.start_watching(
                self._on_distributed_control_command
            )
            logger.info(
                f"[Worker Control] Started watching "
                f"(mode will be auto-detected: Change Streams or Polling)"
            )

        # Start background tasks
        self._heartbeat_task = asyncio.create_task(self._update_heartbeat())
        self._control_monitor_task = asyncio.create_task(self._monitor_control_file())
        
        try:
            # Signal readiness
            self._update_liveness(healthy=True)
            self._update_readiness(ready=True)
            
            # Main processing loop
            while not self._shutdown_event.is_set():
                # Wait if paused
                await self._pause_event.wait()

                try:
                    # Process one batch using worker
                    await self.worker.process_batch()
                    self._last_heartbeat = datetime.now()

                except Exception as e:
                    logger.error(f"Error processing batch: {e}", exc_info=True)
                    self._errors_count += 1
                    # Continue running despite errors
                
                # Interruptible sleep - wakes up on shutdown or timeout
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self.config.poll_interval
                    )
                    # If we get here, shutdown was signaled
                    break
                except asyncio.TimeoutError:
                    # Normal - timeout reached, continue loop
                    pass
        
        finally:
            # Cleanup
            logger.info("Cleaning up agent resources")

            # Stop distributed control watcher
            if self.distributed_control:
                logger.info("[Worker Control] Stopping watch task")
                await self.distributed_control.stop_watching()

            # Cancel background tasks
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass

            if self._control_monitor_task:
                self._control_monitor_task.cancel()
                try:
                    await self._control_monitor_task
                except asyncio.CancelledError:
                    pass

            # Update health status
            self._update_readiness(ready=False)
            self._update_liveness(healthy=False)

            # Close MongoDB connection
            await self.mongo.close()

            # Log final statistics
            stats = self.worker.get_statistics()
            logger.info(f"Agent stopped. Stats: batches={stats['batches_processed']}, "
                       f"documents={stats['documents_processed']}, errors={self._errors_count}")

            self.state = AgentState.STOPPED

    async def _update_heartbeat(self) -> None:
        """Periodically update liveness file timestamp"""
        while True:
            try:
                self._update_liveness(healthy=True)
                await asyncio.sleep(self.config.heartbeat_interval)
            except asyncio.CancelledError:
                logger.debug("Heartbeat task cancelled")
                break
            except Exception as e:
                logger.error(f"Heartbeat update failed: {e}")
                await asyncio.sleep(self.config.heartbeat_interval)
    
    async def _monitor_control_file(self) -> None:
        """Monitor control file for pause/resume/shutdown commands"""
        last_command = None
        
        while True:
            try:
                if self.control_file.exists():
                    command = self.control_file.read_text().strip().lower()
                    
                    # Only process if command changed (avoid repeated processing)
                    if command != last_command:
                        logger.info(f"Control file command detected: {command}")
                        
                        if command == "pause" and self.state == AgentState.RUNNING:
                            logger.info("Executing pause command from control file")
                            self.pause()
                            last_command = command
                        elif command == "resume" and self.state == AgentState.PAUSED:
                            logger.info("Executing resume command from control file")
                            self.resume()
                            last_command = command
                        elif command == "shutdown":
                            logger.info("Executing shutdown command from control file")
                            await self.shutdown()
                            break
                        elif command == "running" and self.state != AgentState.RUNNING:
                            # Handle "running" as resume
                            logger.info("Control file set to 'running', resuming agent")
                            self.resume()
                            last_command = command
                        else:
                            # Invalid or no-op command
                            if command not in ["pause", "resume", "shutdown", "running"]:
                                logger.warning(f"Unknown control command: {command}")
                
                await asyncio.sleep(2)  # Check every 2 seconds
            
            except asyncio.CancelledError:
                logger.debug("Control monitor task cancelled")
                break
            except Exception as e:
                logger.error(f"Control file monitor error: {e}")
                await asyncio.sleep(5)
    
    def _update_liveness(self, healthy: bool) -> None:
        """Update liveness indicator file"""
        try:
            if healthy:
                # Touch file and write status
                stats = self.worker.get_statistics()
                self.liveness_file.write_text(
                    f"{self.state.value}\n"
                    f"{datetime.now().isoformat()}\n"
                    f"batches={stats['batches_processed']}\n"
                    f"documents={stats['documents_processed']}\n"
                    f"errors={self._errors_count}\n"
                )
            else:
                # Remove file to indicate unhealthy
                self.liveness_file.unlink(missing_ok=True)
        except Exception as e:
            logger.error(f"Failed to update liveness file: {e}")
    
    def _update_readiness(self, ready: bool) -> None:
        """Update readiness indicator file"""
        try:
            if ready and self.state == AgentState.RUNNING:
                self.readiness_file.write_text(
                    f"{self.state.value}\n"
                    f"{datetime.now().isoformat()}\n"
                )
            else:
                self.readiness_file.unlink(missing_ok=True)
        except Exception as e:
            logger.error(f"Failed to update readiness file: {e}")
    
    def pause(self) -> None:
        """Pause processing (completes current batch)"""
        if self.state == AgentState.RUNNING:
            logger.info("Pausing agent")
            self.state = AgentState.PAUSED
            self._update_readiness(ready=False)
            self._pause_event.clear()
        else:
            logger.warning(f"Cannot pause from state: {self.state.value}")
    
    def resume(self) -> None:
        """Resume processing"""
        if self.state == AgentState.PAUSED:
            logger.info("Resuming agent")
            self.state = AgentState.RUNNING
            self._update_readiness(ready=True)
            self._pause_event.set()
        else:
            logger.warning(f"Cannot resume from state: {self.state.value}")
    
    async def shutdown(self) -> None:
        """Initiate graceful shutdown"""
        if self.state in [AgentState.STOPPING, AgentState.STOPPED]:
            logger.warning(f"Already shutting down (state: {self.state.value})")
            return
        
        logger.info("Initiating graceful shutdown")
        self.state = AgentState.STOPPING
        self._update_readiness(ready=False)
        self._shutdown_event.set()
