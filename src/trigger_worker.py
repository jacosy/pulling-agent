"""
Service logic for processing trigger documents from MongoDB.
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

from .config import AgentConfig
from .mongo_client import MongoClientManager

logger = logging.getLogger(__name__)


class TriggerWorker:
    """
    Worker responsible for processing trigger documents from MongoDB.

    This class contains the business logic for:
    - Fetching pending documents in batches
    - Processing individual documents
    - Updating document status (pending -> processed/failed)

    Separated from agent infrastructure to allow independent testing
    and potential reuse in different contexts.
    """

    def __init__(self, config: AgentConfig, mongo_manager: MongoClientManager):
        """
        Initialize the trigger worker.

        Args:
            config: Agent configuration
            mongo_manager: MongoDB client manager
        """
        self.config = config
        self.mongo = mongo_manager

        # Statistics
        self.batches_processed = 0
        self.documents_processed = 0

    async def process_batch(self) -> int:
        """
        Pull and process one batch of documents from MongoDB.

        Returns:
            Number of documents processed in this batch

        Raises:
            Exception: If batch processing fails
        """
        try:
            # Find pending documents
            cursor = self.mongo.collection.find(
                {"status": "pending"},
                limit=self.config.batch_size
            )

            documents = await cursor.to_list(length=self.config.batch_size)

            if not documents:
                logger.debug("No pending documents found")
                return 0

            logger.info(f"Processing batch of {len(documents)} documents")

            # Process each document
            processed_count = 0
            for doc in documents:
                try:
                    # Process the document
                    await self.process_document(doc)

                    # Mark as processed
                    await self.mongo.collection.update_one(
                        {"_id": doc["_id"]},
                        {
                            "$set": {
                                "status": "processed",
                                "processed_at": datetime.utcnow()
                            }
                        }
                    )

                    self.documents_processed += 1
                    processed_count += 1

                except Exception as e:
                    logger.error(f"Failed to process document {doc.get('_id')}: {e}")

                    # Mark as failed
                    await self.mongo.collection.update_one(
                        {"_id": doc["_id"]},
                        {
                            "$set": {
                                "status": "failed",
                                "error": str(e),
                                "failed_at": datetime.utcnow()
                            }
                        }
                    )

            self.batches_processed += 1
            logger.info(f"Batch completed. Processed {processed_count}/{len(documents)} documents. "
                       f"Total: {self.batches_processed} batches, "
                       f"{self.documents_processed} documents")

            return processed_count

        except Exception as e:
            logger.error(f"Batch processing failed: {e}", exc_info=True)
            raise

    async def process_document(self, document: dict) -> None:
        """
        Process a single document.

        TODO: Implement your business logic here.

        Args:
            document: MongoDB document to process

        Raises:
            Exception: If document processing fails
        """
        # Placeholder - add your processing logic
        logger.debug(f"Processing document: {document.get('_id')}")

        # Simulate some work
        await asyncio.sleep(0.01)

        # Example: You might want to:
        # - Validate document structure
        # - Make API calls
        # - Transform data
        # - Send notifications
        # - etc.

    def get_statistics(self) -> dict:
        """
        Get processing statistics.

        Returns:
            Dictionary with batches_processed and documents_processed
        """
        return {
            "batches_processed": self.batches_processed,
            "documents_processed": self.documents_processed
        }
