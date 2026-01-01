"""
MongoDB client management.
"""
import logging
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

logger = logging.getLogger(__name__)


class MongoClientManager:
    """Manages MongoDB connection lifecycle"""
    
    def __init__(self, uri: str, database: str, collection: str):
        self.uri = uri
        self.database_name = database
        self.collection_name = collection
        self._client: Optional[AsyncIOMotorClient] = None
        self._collection: Optional[AsyncIOMotorCollection] = None
    
    async def connect(self) -> None:
        """Establish MongoDB connection"""
        try:
            logger.info(f"Connecting to MongoDB: {self.database_name}.{self.collection_name}")
            self._client = AsyncIOMotorClient(self.uri)
            
            # Test connection
            await self._client.admin.command('ping')
            
            # Get collection reference
            db = self._client[self.database_name]
            self._collection = db[self.collection_name]
            
            logger.info("MongoDB connection established")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
    
    async def close(self) -> None:
        """Close MongoDB connection"""
        if self._client:
            logger.info("Closing MongoDB connection")
            self._client.close()
            self._client = None
            self._collection = None
    
    @property
    def collection(self) -> AsyncIOMotorCollection:
        """Get the collection instance"""
        if self._collection is None:
            raise RuntimeError("MongoDB client not connected. Call connect() first.")
        return self._collection
    
    @property
    def is_connected(self) -> bool:
        """Check if client is connected"""
        return self._client is not None and self._collection is not None
