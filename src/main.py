"""
Main entry point for the pulling agent.
"""
import asyncio
import logging
import sys

from .config import AgentConfig
from .mongo_client import MongoClientManager
from .agent import PullingAgent


def setup_logging(log_level: str) -> None:
    """Configure logging"""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


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
    
    # Create and run agent
    agent = PullingAgent(config, mongo_manager)
    
    try:
        await agent.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Agent failed with error: {e}", exc_info=True)
        sys.exit(1)
    
    logger.info("Application shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
