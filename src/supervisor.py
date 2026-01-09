"""
Supervisor module for managing and restarting application components.

This module provides crash recovery and automatic restart capabilities
for the API server and agent components.
"""
import asyncio
import logging
from typing import Callable, Awaitable, Optional
from datetime import datetime
from enum import Enum


logger = logging.getLogger(__name__)


class ComponentState(Enum):
    """State of a supervised component"""
    STARTING = "starting"
    RUNNING = "running"
    CRASHED = "crashed"
    RESTARTING = "restarting"
    STOPPED = "stopped"


class SupervisedComponent:
    """
    Wraps a component with automatic restart on failure.

    Features:
    - Automatic restart on crash
    - Exponential backoff between restarts
    - Maximum restart attempts limit
    - Detailed crash logging
    """

    def __init__(
        self,
        name: str,
        component_func: Callable[[], Awaitable[None]],
        max_restarts: int = 10,
        max_backoff: float = 60.0,
        initial_backoff: float = 1.0,
        backoff_multiplier: float = 2.0
    ):
        """
        Initialize supervised component.

        Args:
            name: Component name for logging
            component_func: Async function to run (the component)
            max_restarts: Maximum number of restart attempts
            max_backoff: Maximum backoff time in seconds
            initial_backoff: Initial backoff time in seconds
            backoff_multiplier: Multiplier for exponential backoff
        """
        self.name = name
        self.component_func = component_func
        self.max_restarts = max_restarts
        self.max_backoff = max_backoff
        self.initial_backoff = initial_backoff
        self.backoff_multiplier = backoff_multiplier

        self.state = ComponentState.STOPPED
        self.restart_count = 0
        self.crash_count = 0
        self.last_crash_time: Optional[datetime] = None
        self.start_time: Optional[datetime] = None
        self._task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

    async def _run_with_monitoring(self) -> None:
        """Run component with crash monitoring and restart logic."""
        current_backoff = self.initial_backoff

        while not self._shutdown_event.is_set():
            try:
                self.state = ComponentState.STARTING
                self.start_time = datetime.now()
                logger.info(f"[{self.name}] Starting (attempt {self.restart_count + 1})")

                self.state = ComponentState.RUNNING
                await self.component_func()

                # If component exits normally, we're done
                logger.info(f"[{self.name}] Exited normally")
                self.state = ComponentState.STOPPED
                break

            except asyncio.CancelledError:
                logger.info(f"[{self.name}] Cancelled, shutting down")
                self.state = ComponentState.STOPPED
                raise

            except Exception as e:
                self.crash_count += 1
                self.last_crash_time = datetime.now()
                uptime = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0

                logger.error(
                    f"[{self.name}] Crashed after {uptime:.1f}s (crash #{self.crash_count}): {e}",
                    exc_info=True
                )

                self.state = ComponentState.CRASHED

                # Check if we should restart
                if self.restart_count >= self.max_restarts:
                    logger.critical(
                        f"[{self.name}] Maximum restart attempts ({self.max_restarts}) reached. "
                        "Component will not be restarted."
                    )
                    self.state = ComponentState.STOPPED
                    raise RuntimeError(f"{self.name} exceeded maximum restart attempts")

                # Calculate backoff time
                wait_time = min(current_backoff, self.max_backoff)
                logger.info(
                    f"[{self.name}] Restarting in {wait_time:.1f}s "
                    f"(restart {self.restart_count + 1}/{self.max_restarts})"
                )

                self.state = ComponentState.RESTARTING

                # Wait with interruptible sleep
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=wait_time
                    )
                    # Shutdown was signaled during backoff
                    logger.info(f"[{self.name}] Shutdown requested during restart backoff")
                    self.state = ComponentState.STOPPED
                    break
                except asyncio.TimeoutError:
                    # Normal - timeout reached, proceed with restart
                    pass

                # Increase backoff for next time
                current_backoff *= self.backoff_multiplier
                self.restart_count += 1

        logger.info(f"[{self.name}] Monitoring loop exited")

    async def start(self) -> None:
        """Start the supervised component."""
        if self._task is not None:
            logger.warning(f"[{self.name}] Already started")
            return

        logger.info(f"[{self.name}] Starting supervision")
        self._shutdown_event.clear()
        self._task = asyncio.create_task(self._run_with_monitoring())

    async def stop(self) -> None:
        """Stop the supervised component gracefully."""
        logger.info(f"[{self.name}] Stopping...")
        self._shutdown_event.set()

        if self._task:
            # Cancel the task
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"[{self.name}] Error during shutdown: {e}")

        self.state = ComponentState.STOPPED
        logger.info(f"[{self.name}] Stopped")

    async def wait(self) -> None:
        """Wait for the component task to complete."""
        if self._task:
            await self._task

    def get_stats(self) -> dict:
        """Get component statistics."""
        uptime = None
        if self.start_time and self.state == ComponentState.RUNNING:
            uptime = (datetime.now() - self.start_time).total_seconds()

        return {
            "name": self.name,
            "state": self.state.value,
            "restart_count": self.restart_count,
            "crash_count": self.crash_count,
            "last_crash_time": self.last_crash_time.isoformat() if self.last_crash_time else None,
            "uptime_seconds": uptime
        }


class Supervisor:
    """
    Supervisor for managing multiple components with automatic restart.

    Monitors all components and can restart them independently on failure.
    """

    def __init__(self):
        """Initialize the supervisor."""
        self.components: dict[str, SupervisedComponent] = {}
        self._shutdown_event = asyncio.Event()
        self._monitor_task: Optional[asyncio.Task] = None

    def add_component(
        self,
        name: str,
        component_func: Callable[[], Awaitable[None]],
        max_restarts: int = 10,
        max_backoff: float = 60.0
    ) -> SupervisedComponent:
        """
        Add a component to be supervised.

        Args:
            name: Component name
            component_func: Async function to run
            max_restarts: Maximum restart attempts
            max_backoff: Maximum backoff time in seconds

        Returns:
            The supervised component
        """
        if name in self.components:
            raise ValueError(f"Component '{name}' already exists")

        component = SupervisedComponent(
            name=name,
            component_func=component_func,
            max_restarts=max_restarts,
            max_backoff=max_backoff
        )
        self.components[name] = component
        logger.info(f"Added component '{name}' to supervisor")
        return component

    async def _monitor_components(self) -> None:
        """Monitor components and trigger shutdown if any fail permanently."""
        while not self._shutdown_event.is_set():
            try:
                # Wait for any component task to complete
                if self.components:
                    tasks = [c._task for c in self.components.values() if c._task]
                    if tasks:
                        done, pending = await asyncio.wait(
                            tasks,
                            timeout=1.0,
                            return_when=asyncio.FIRST_COMPLETED
                        )

                        # Check if any task completed with an error
                        for task in done:
                            try:
                                await task
                            except Exception as e:
                                # A component failed permanently
                                logger.critical(f"Component failed permanently: {e}")
                                self._shutdown_event.set()
                                return
                    else:
                        await asyncio.sleep(1.0)
                else:
                    await asyncio.sleep(1.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in component monitor: {e}", exc_info=True)
                await asyncio.sleep(1.0)

    async def start_all(self) -> None:
        """Start all supervised components."""
        logger.info("Starting all supervised components")
        for component in self.components.values():
            await component.start()

        # Start monitoring task
        self._monitor_task = asyncio.create_task(self._monitor_components())

    async def stop_all(self) -> None:
        """Stop all supervised components gracefully."""
        logger.info("Stopping all supervised components")
        self._shutdown_event.set()

        # Cancel monitor task
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        # Stop all components concurrently
        await asyncio.gather(
            *[component.stop() for component in self.components.values()],
            return_exceptions=True
        )

    async def wait_for_shutdown(self) -> None:
        """Wait until a shutdown is triggered (by signal or component failure)."""
        await self._shutdown_event.wait()

    async def wait_all(self) -> None:
        """Wait for all components to complete."""
        if not self.components:
            return

        # Wait for all components
        await asyncio.gather(
            *[component.wait() for component in self.components.values()],
            return_exceptions=True
        )

    def get_all_stats(self) -> dict:
        """Get statistics for all components."""
        return {
            name: component.get_stats()
            for name, component in self.components.items()
        }
