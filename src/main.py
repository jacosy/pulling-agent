"""
Main entry point for the pulling agent.
"""
import asyncio
import logging
import sys
import os

from .config import AgentConfig
from .mongo_client import MongoClientManager
from .agent import PullingAgent
from .api import create_api

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
    """Main application entry point"""
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

    logger.info(f"Starting API server on {api_host}:{api_port}")
    logger.info("Starting pulling agent")

    try:
        # Run both agent and API server concurrently
        await asyncio.gather(
            agent.run(),
            run_api_server(api_app, api_host, api_port)
        )
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Application failed with error: {e}", exc_info=True)
        sys.exit(1)

    logger.info("Application shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
