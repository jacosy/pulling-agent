"""
Unit tests for the trigger worker.
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from src.trigger_worker import TriggerWorker
from src.config import AgentConfig
from src.mongo_client import MongoClientManager


@pytest.fixture
def config():
    """Create test configuration"""
    return AgentConfig(
        mongodb_uri="mongodb://localhost:27017",
        mongodb_database="testdb",
        mongodb_collection="testcollection",
        poll_interval=1,
        batch_size=10,
        shutdown_timeout=5,
        heartbeat_interval=1,
        log_level="DEBUG"
    )


@pytest.fixture
def mongo_manager(config):
    """Create mock MongoDB manager"""
    manager = MagicMock(spec=MongoClientManager)
    manager.collection = MagicMock()
    return manager


@pytest.fixture
def worker(config, mongo_manager):
    """Create worker instance for testing"""
    return TriggerWorker(config, mongo_manager)


class TestTriggerWorker:
    """Tests for TriggerWorker"""

    @pytest.mark.asyncio
    async def test_worker_initialization(self, worker):
        """Test worker initializes correctly"""
        assert worker.batches_processed == 0
        assert worker.documents_processed == 0

    @pytest.mark.asyncio
    async def test_process_batch_no_documents(self, worker, mongo_manager):
        """Test processing when no documents are pending"""
        # Mock empty result
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mongo_manager.collection.find.return_value = mock_cursor

        # Process batch
        result = await worker.process_batch()

        # Verify
        assert result == 0
        assert worker.batches_processed == 0
        assert worker.documents_processed == 0

    @pytest.mark.asyncio
    async def test_process_batch_with_documents(self, worker, mongo_manager):
        """Test processing a batch with documents"""
        # Mock documents
        test_docs = [
            {"_id": "doc1", "status": "pending"},
            {"_id": "doc2", "status": "pending"},
            {"_id": "doc3", "status": "pending"}
        ]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=test_docs)
        mongo_manager.collection.find.return_value = mock_cursor
        mongo_manager.collection.update_one = AsyncMock()

        # Process batch
        result = await worker.process_batch()

        # Verify
        assert result == 3
        assert worker.batches_processed == 1
        assert worker.documents_processed == 3
        assert mongo_manager.collection.update_one.call_count == 3

    @pytest.mark.asyncio
    async def test_process_batch_with_failures(self, worker, mongo_manager):
        """Test batch processing handles document failures"""
        # Mock documents
        test_docs = [
            {"_id": "doc1", "status": "pending"},
            {"_id": "doc2", "status": "pending"}
        ]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=test_docs)
        mongo_manager.collection.find.return_value = mock_cursor

        # Mock update to fail on first document
        update_calls = 0

        async def mock_update(*args, **kwargs):
            nonlocal update_calls
            update_calls += 1
            return MagicMock()

        mongo_manager.collection.update_one = AsyncMock(side_effect=mock_update)

        # Mock process_document to fail on first doc
        original_process = worker.process_document
        call_count = [0]

        async def failing_process(doc):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("Test error")
            await original_process(doc)

        worker.process_document = failing_process

        # Process batch
        result = await worker.process_batch()

        # Verify: one failed, one succeeded
        assert result == 1  # Only one successful
        assert worker.batches_processed == 1
        assert worker.documents_processed == 1
        assert mongo_manager.collection.update_one.call_count == 2  # One failure, one success

    @pytest.mark.asyncio
    async def test_process_document(self, worker):
        """Test processing a single document"""
        test_doc = {"_id": "test_doc", "data": "test_data"}

        # Should not raise
        await worker.process_document(test_doc)

    @pytest.mark.asyncio
    async def test_get_statistics(self, worker, mongo_manager):
        """Test getting worker statistics"""
        # Process some batches
        test_docs = [{"_id": f"doc{i}", "status": "pending"} for i in range(5)]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=test_docs)
        mongo_manager.collection.find.return_value = mock_cursor
        mongo_manager.collection.update_one = AsyncMock()

        await worker.process_batch()
        await worker.process_batch()

        # Get statistics
        stats = worker.get_statistics()

        assert stats["batches_processed"] == 2
        assert stats["documents_processed"] == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
