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

            return StatsResponse(
                state=self.agent.state.value,
                batches_processed=self.agent._batches_processed,
                documents_processed=self.agent._documents_processed,
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
