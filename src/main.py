"""
Main entry point for the pulling agent.
"""
import asyncio
import logging
import sys
import os
import signal

from .config import AgentConfig
from .mongo_client import MongoClientManager
from .agent import PullingAgent
from .api import create_api
from .supervisor import Supervisor

import uvicorn


def setup_logging(log_level: str) -> None:
    """Configure logging"""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


async def run_api_server(app, host: str, port: int) -> None:
    """Run FastAPI server using uvicorn"""
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    """Main application entry point with supervised components"""
    # Load configuration from environment
    config = AgentConfig.from_env()

    # Setup logging
    setup_logging(config.log_level)
    logger = logging.getLogger(__name__)

    try:
        # Validate configuration
        config.validate()
        logger.info("Configuration validated successfully")
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    # Create MongoDB manager
    mongo_manager = MongoClientManager(
        uri=config.mongodb_uri,
        database=config.mongodb_database,
        collection=config.mongodb_collection
    )

    # Create agent
    agent = PullingAgent(config, mongo_manager)

    # Create FastAPI app
    api_app = create_api(agent)

    # Get API server configuration from environment
    api_host = os.getenv("API_HOST", "0.0.0.0")
    api_port = int(os.getenv("API_PORT", "8000"))

    # Create supervisor for crash recovery
    supervisor = Supervisor()

    # Add agent as supervised component
    supervisor.add_component(
        name="agent",
        component_func=agent.run,
        max_restarts=config.max_component_restarts,
        max_backoff=config.restart_backoff_max
    )

    # Add API server as supervised component
    supervisor.add_component(
        name="api-server",
        component_func=lambda: run_api_server(api_app, api_host, api_port),
        max_restarts=config.max_component_restarts,
        max_backoff=config.restart_backoff_max
    )

    # Setup signal handlers for graceful shutdown
    def signal_handler(sig):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signal.Signals(sig).name}, initiating shutdown")
        supervisor._shutdown_event.set()

    # Register signal handlers
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))

    logger.info(f"Starting supervised API server on {api_host}:{api_port}")
    logger.info("Starting supervised pulling agent")
    logger.info(f"Components will auto-restart up to {config.max_component_restarts} times on crash")

    try:
        # Start all supervised components
        await supervisor.start_all()

        # Wait for shutdown signal or component failure
        await supervisor.wait_for_shutdown()

        logger.info("Shutdown initiated, stopping all components")

    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Application failed with error: {e}", exc_info=True)
    finally:
        # Stop all supervised components
        await supervisor.stop_all()

        # Log final statistics
        stats = supervisor.get_all_stats()
        logger.info("Final component statistics:")
        for component_name, component_stats in stats.items():
            logger.info(
                f"  {component_name}: "
                f"state={component_stats['state']}, "
                f"crashes={component_stats['crash_count']}, "
                f"restarts={component_stats['restart_count']}"
            )

    logger.info("Application shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
