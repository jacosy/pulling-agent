"""
FastAPI endpoints for agent control and monitoring.

Replaces kubectl exec operations with HTTP API endpoints.
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import AgentState

logger = logging.getLogger(__name__)

# Request/Response models
class AgentStateResponse(BaseModel):
    """Agent state response"""
    state: str
    timestamp: str

class StatsResponse(BaseModel):
    """Processing statistics response"""
    state: str
    batches_processed: int
    documents_processed: int
    errors_count: int
    last_heartbeat: str
    uptime_seconds: Optional[float] = None

class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    timestamp: str
    state: Optional[str] = None

class ConfigResponse(BaseModel):
    """Configuration response"""
    mongodb_database: str
    mongodb_collection: str
    poll_interval: int
    batch_size: int
    heartbeat_interval: int
    log_level: str

class MessageResponse(BaseModel):
    """Generic message response"""
    message: str
    state: Optional[str] = None

class ClusterCommandResponse(BaseModel):
    """Cluster command response"""
    status: str
    message: str
    command: str
    version: int
    timestamp: str
    reason: str
    propagation: str

class ClusterStateResponse(BaseModel):
    """Cluster control state response"""
    command: str
    version: int
    timestamp: str
    reason: str
    updated_by: str
    watch_mode: Optional[str] = None
    note: str


class AgentAPI:
    """
    FastAPI application for agent control and monitoring.

    Provides HTTP endpoints to replace kubectl exec operations:
    - POST /api/agent/pause - Pause processing
    - POST /api/agent/resume - Resume processing
    - POST /api/agent/shutdown - Graceful shutdown
    - GET /api/agent/state - Get current state
    - GET /api/stats - Get processing statistics
    - GET /health - Liveness check
    - GET /readiness - Readiness check
    - GET /api/config - Get configuration
    """

    def __init__(self, agent):
        """
        Initialize API with reference to agent.

        Args:
            agent: PullingAgent instance to control
        """
        self.agent = agent
        self.app = FastAPI(
            title="Pulling Agent API",
            description="HTTP API for controlling and monitoring the MongoDB pulling agent",
            version="1.0.0"
        )
        self.start_time = datetime.now()
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Setup all API routes"""

        @self.app.get("/", response_model=Dict[str, str])
        async def root():
            """API root - basic info"""
            return {
                "service": "Pulling Agent API",
                "version": "1.0.0",
                "status": "running"
            }

        @self.app.get("/health", response_model=HealthResponse)
        async def health():
            """
            Liveness probe - checks if agent is alive.

            Returns 200 if agent is running, regardless of paused state.
            """
            return HealthResponse(
                status="healthy",
                timestamp=datetime.now().isoformat(),
                state=self.agent.state.value
            )

        @self.app.get("/readiness", response_model=HealthResponse)
        async def readiness():
            """
            Readiness probe - checks if agent is ready to process.

            Returns 200 only if agent is in RUNNING state.
            Returns 503 if agent is PAUSED, STOPPING, or STOPPED.
            """
            if self.agent.state == AgentState.RUNNING:
                return HealthResponse(
                    status="ready",
                    timestamp=datetime.now().isoformat(),
                    state=self.agent.state.value
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Agent not ready (state: {self.agent.state.value})"
                )

        @self.app.get("/api/agent/state", response_model=AgentStateResponse)
        async def get_state():
            """
            Get current agent state.

            Returns: Current state (RUNNING, PAUSED, STOPPING, STOPPED)
            """
            return AgentStateResponse(
                state=self.agent.state.value,
                timestamp=datetime.now().isoformat()
            )

        @self.app.post("/api/agent/pause", response_model=MessageResponse)
        async def pause():
            """
            Pause agent processing.

            Replaces: kubectl exec $POD -- kill -USR1 1

            Returns 200 if paused successfully.
            Returns 400 if agent cannot be paused from current state.
            """
            if self.agent.state == AgentState.RUNNING:
                self.agent.pause()
                logger.info("Agent paused via API")
                return MessageResponse(
                    message="Agent paused successfully",
                    state=self.agent.state.value
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot pause from state: {self.agent.state.value}"
                )

        @self.app.post("/api/agent/resume", response_model=MessageResponse)
        async def resume():
            """
            Resume agent processing.

            Replaces: kubectl exec $POD -- kill -USR2 1

            Returns 200 if resumed successfully.
            Returns 400 if agent cannot be resumed from current state.
            """
            if self.agent.state == AgentState.PAUSED:
                self.agent.resume()
                logger.info("Agent resumed via API")
                return MessageResponse(
                    message="Agent resumed successfully",
                    state=self.agent.state.value
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot resume from state: {self.agent.state.value}"
                )

        @self.app.post("/api/agent/shutdown", response_model=MessageResponse)
        async def shutdown():
            """
            Initiate graceful shutdown.

            Replaces: kubectl exec $POD -- kill -TERM 1

            Returns 202 (Accepted) as shutdown is asynchronous.
            """
            if self.agent.state not in [AgentState.STOPPING, AgentState.STOPPED]:
                # Note: We don't await shutdown() as it's a long-running operation
                # The agent will handle shutdown gracefully in its own task
                import asyncio
                asyncio.create_task(self.agent.shutdown())
                logger.info("Agent shutdown initiated via API")
                return JSONResponse(
                    status_code=status.HTTP_202_ACCEPTED,
                    content={
                        "message": "Shutdown initiated",
                        "state": AgentState.STOPPING.value
                    }
                )
            else:
                return MessageResponse(
                    message=f"Already shutting down (state: {self.agent.state.value})",
                    state=self.agent.state.value
                )

        @self.app.get("/api/stats", response_model=StatsResponse)
        async def get_stats():
            """
            Get processing statistics.

            Replaces: kubectl exec $POD -- cat /tmp/health/liveness

            Returns comprehensive statistics including:
            - Current state
            - Batches processed
            - Documents processed
            - Error count
            - Last heartbeat time
            - Uptime
            """
            uptime = (datetime.now() - self.start_time).total_seconds()
            worker_stats = self.agent.worker.get_statistics()

            return StatsResponse(
                state=self.agent.state.value,
                batches_processed=worker_stats['batches_processed'],
                documents_processed=worker_stats['documents_processed'],
                errors_count=self.agent._errors_count,
                last_heartbeat=self.agent._last_heartbeat.isoformat(),
                uptime_seconds=uptime
            )

        @self.app.get("/api/config", response_model=ConfigResponse)
        async def get_config():
            """
            Get current agent configuration (non-sensitive).

            Returns configuration values without exposing secrets like MongoDB URI.
            """
            return ConfigResponse(
                mongodb_database=self.agent.config.mongodb_database,
                mongodb_collection=self.agent.config.mongodb_collection,
                poll_interval=self.agent.config.poll_interval,
                batch_size=self.agent.config.batch_size,
                heartbeat_interval=self.agent.config.heartbeat_interval,
                log_level=self.agent.config.log_level
            )

        @self.app.get("/api/mongo/status", response_model=Dict[str, Any])
        async def mongo_status():
            """
            Check MongoDB connection status.

            Replaces: kubectl exec $POD -- python3 -c "..."

            Returns connection status and basic info.
            """
            try:
                # Attempt a simple ping to verify connection
                result = await self.agent.mongo.client.admin.command('ping')

                return {
                    "connected": True,
                    "database": self.agent.config.mongodb_database,
                    "collection": self.agent.config.mongodb_collection,
                    "ping_response": result
                }
            except Exception as e:
                logger.error(f"MongoDB status check failed: {e}")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"MongoDB connection error: {str(e)}"
                )

        # ========== CLUSTER CONTROL ENDPOINTS ==========
        # These endpoints control ALL agents in the cluster via distributed coordination

        @self.app.post("/api/cluster/pause", response_model=ClusterCommandResponse)
        async def pause_all_agents(reason: str = "Manual cluster pause", updated_by: str = "api_user"):
            """
            Pause ALL agents in the cluster.

            This uses MongoDB-based distributed control to coordinate all agent instances.
            The command is propagated via:
            - MongoDB Change Streams (event-driven, sub-second latency) if available, OR
            - Polling (configurable interval, default 10s) as fallback

            Args:
                reason: Human-readable reason for the pause
                updated_by: Who/what is issuing this command (for audit)

            Returns:
                Command acknowledgment with version number

            Note:
                - All agents will pause after completing their current batch
                - Agents will receive the command within seconds
                - Command survives pod restarts
            """
            if not self.agent.distributed_control:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Distributed control is not enabled on this agent"
                )

            try:
                result = await self.agent.distributed_control.set_global_command(
                    command="pause",
                    reason=reason,
                    updated_by=updated_by
                )

                watch_mode = self.agent.distributed_control.get_watch_mode()
                propagation = (
                    "Agents will pause within seconds (event-driven via Change Streams)"
                    if watch_mode == "change_streams"
                    else f"Agents will pause within {self.agent.config.control_polling_interval}s (polling mode)"
                )

                logger.info(f"[Cluster Control] Pause command issued by {updated_by}: {reason}")

                return ClusterCommandResponse(
                    status="success",
                    message="Pause command issued to all agents in the cluster",
                    command="pause",
                    version=result["version"],
                    timestamp=result["timestamp"].isoformat(),
                    reason=reason,
                    propagation=propagation
                )

            except Exception as e:
                logger.error(f"Failed to set cluster pause command: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to issue cluster pause: {str(e)}"
                )

        @self.app.post("/api/cluster/resume", response_model=ClusterCommandResponse)
        async def resume_all_agents(reason: str = "Manual cluster resume", updated_by: str = "api_user"):
            """
            Resume ALL agents in the cluster.

            This uses MongoDB-based distributed control to coordinate all agent instances.
            The command is propagated via:
            - MongoDB Change Streams (event-driven, sub-second latency) if available, OR
            - Polling (configurable interval, default 10s) as fallback

            Args:
                reason: Human-readable reason for the resume
                updated_by: Who/what is issuing this command (for audit)

            Returns:
                Command acknowledgment with version number

            Note:
                - All agents will resume processing immediately
                - Agents will receive the command within seconds
                - Command survives pod restarts
            """
            if not self.agent.distributed_control:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Distributed control is not enabled on this agent"
                )

            try:
                result = await self.agent.distributed_control.set_global_command(
                    command="running",
                    reason=reason,
                    updated_by=updated_by
                )

                watch_mode = self.agent.distributed_control.get_watch_mode()
                propagation = (
                    "Agents will resume within seconds (event-driven via Change Streams)"
                    if watch_mode == "change_streams"
                    else f"Agents will resume within {self.agent.config.control_polling_interval}s (polling mode)"
                )

                logger.info(f"[Cluster Control] Resume command issued by {updated_by}: {reason}")

                return ClusterCommandResponse(
                    status="success",
                    message="Resume command issued to all agents in the cluster",
                    command="running",
                    version=result["version"],
                    timestamp=result["timestamp"].isoformat(),
                    reason=reason,
                    propagation=propagation
                )

            except Exception as e:
                logger.error(f"Failed to set cluster resume command: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to issue cluster resume: {str(e)}"
                )

        @self.app.post("/api/cluster/shutdown", response_model=ClusterCommandResponse)
        async def shutdown_all_agents(reason: str = "Manual cluster shutdown", updated_by: str = "api_user"):
            """
            Gracefully shutdown ALL agents in the cluster.

            This uses MongoDB-based distributed control to coordinate all agent instances.
            The command is propagated via:
            - MongoDB Change Streams (event-driven, sub-second latency) if available, OR
            - Polling (configurable interval, default 10s) as fallback

            Args:
                reason: Human-readable reason for the shutdown
                updated_by: Who/what is issuing this command (for audit)

            Returns:
                Command acknowledgment with version number

            Warning:
                This will shutdown ALL agents in the cluster. Use with caution!
            """
            if not self.agent.distributed_control:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Distributed control is not enabled on this agent"
                )

            try:
                result = await self.agent.distributed_control.set_global_command(
                    command="shutdown",
                    reason=reason,
                    updated_by=updated_by
                )

                watch_mode = self.agent.distributed_control.get_watch_mode()
                propagation = (
                    "Agents will shutdown gracefully within seconds (event-driven via Change Streams)"
                    if watch_mode == "change_streams"
                    else f"Agents will shutdown within {self.agent.config.control_polling_interval}s (polling mode)"
                )

                logger.warning(f"[Cluster Control] SHUTDOWN command issued by {updated_by}: {reason}")

                return ClusterCommandResponse(
                    status="success",
                    message="Shutdown command issued to all agents in the cluster",
                    command="shutdown",
                    version=result["version"],
                    timestamp=result["timestamp"].isoformat(),
                    reason=reason,
                    propagation=propagation
                )

            except Exception as e:
                logger.error(f"Failed to set cluster shutdown command: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to issue cluster shutdown: {str(e)}"
                )

        @self.app.get("/api/cluster/control-state", response_model=ClusterStateResponse)
        async def get_cluster_control_state():
            """
            Get the current global control state for the cluster.

            Returns the command that all agents are currently subscribed to.
            This shows what command is actively coordinating the cluster.

            Returns:
                Current cluster control state including:
                - command: Current global command (running/pause/shutdown)
                - version: Version number (increments on each change)
                - timestamp: When the command was issued
                - reason: Why the command was issued
                - updated_by: Who issued the command
                - watch_mode: How agents are watching (change_streams or polling)
            """
            if not self.agent.distributed_control:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Distributed control is not enabled on this agent"
                )

            try:
                current = await self.agent.distributed_control.get_current_command()

                if not current:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Control state not initialized"
                    )

                watch_mode = self.agent.distributed_control.get_watch_mode()

                return ClusterStateResponse(
                    command=current["command"],
                    version=current["version"],
                    timestamp=current["timestamp"].isoformat(),
                    reason=current.get("reason", ""),
                    updated_by=current.get("updated_by", "unknown"),
                    watch_mode=watch_mode,
                    note="All agents in the cluster are subscribed to this state"
                )

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to get cluster control state: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to get cluster state: {str(e)}"
                )

        @self.app.get("/api/cluster/stats", response_model=Dict[str, Any])
        async def get_cluster_stats():
            """
            Get distributed control system statistics.

            Returns information about how the distributed control is operating:
            - Watch mode (Change Streams vs polling)
            - Current global command
            - Polling interval (if using polling)
            - Version and timing information
            """
            if not self.agent.distributed_control:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Distributed control is not enabled on this agent"
                )

            try:
                stats = await self.agent.distributed_control.get_stats()
                return stats

            except Exception as e:
                logger.error(f"Failed to get cluster stats: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to get cluster stats: {str(e)}"
                )


def create_api(agent) -> FastAPI:
    """
    Factory function to create FastAPI app.

    Args:
        agent: PullingAgent instance

    Returns:
        FastAPI application instance
    """
    api = AgentAPI(agent)
    return api.app
