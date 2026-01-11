"""
Tests for distributed control coordinator.
"""
import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from motor.motor_asyncio import AsyncIOMotorClient

from src.distributed_control import DistributedControlCoordinator


@pytest.fixture
def mock_mongo_client():
    """Mock MongoDB client"""
    client = AsyncMock(spec=AsyncIOMotorClient)
    db = AsyncMock()
    collection = AsyncMock()

    client.__getitem__.return_value = db
    db.__getitem__.return_value = collection

    return client, db, collection


@pytest.mark.asyncio
async def test_initialize_creates_document(mock_mongo_client):
    """Test initialization creates control document if not exists"""
    client, db, collection = mock_mongo_client

    # Mock collection.find_one to return None (no existing document)
    collection.find_one.return_value = None
    collection.create_index.return_value = None
    collection.insert_one.return_value = Mock()

    coordinator = DistributedControlCoordinator(
        mongo_client=client,
        db_name="test_db",
        polling_interval=10
    )

    await coordinator.initialize()

    # Verify index creation
    collection.create_index.assert_called_once_with("version")

    # Verify document insertion
    collection.insert_one.assert_called_once()
    inserted_doc = collection.insert_one.call_args[0][0]
    assert inserted_doc["_id"] == "global_control"
    assert inserted_doc["command"] == "running"
    assert inserted_doc["version"] == 1
    assert inserted_doc["reason"] == "Initial state"
    assert inserted_doc["updated_by"] == "system"


@pytest.mark.asyncio
async def test_initialize_uses_existing_document(mock_mongo_client):
    """Test initialization uses existing control document"""
    client, db, collection = mock_mongo_client

    existing_doc = {
        "_id": "global_control",
        "command": "pause",
        "version": 42,
        "timestamp": datetime.utcnow(),
        "reason": "Test reason"
    }

    collection.find_one.return_value = existing_doc
    collection.create_index.return_value = None

    coordinator = DistributedControlCoordinator(
        mongo_client=client,
        db_name="test_db"
    )

    await coordinator.initialize()

    # Should NOT insert a new document
    collection.insert_one.assert_not_called()

    # Should track the existing version
    assert coordinator._last_version == 42


@pytest.mark.asyncio
async def test_set_global_command_updates_document(mock_mongo_client):
    """Test setting global command updates MongoDB document"""
    client, db, collection = mock_mongo_client

    updated_doc = {
        "_id": "global_control",
        "command": "pause",
        "version": 2,
        "timestamp": datetime.utcnow(),
        "reason": "Maintenance",
        "updated_by": "ops_team"
    }

    collection.find_one_and_update.return_value = updated_doc

    coordinator = DistributedControlCoordinator(
        mongo_client=client,
        db_name="test_db"
    )

    result = await coordinator.set_global_command(
        command="pause",
        reason="Maintenance",
        updated_by="ops_team"
    )

    # Verify update was called with correct parameters
    collection.find_one_and_update.assert_called_once()
    call_args = collection.find_one_and_update.call_args

    assert call_args[0][0] == {"_id": "global_control"}
    assert "$inc" in call_args[0][1]
    assert call_args[0][1]["$inc"]["version"] == 1
    assert call_args[0][1]["$set"]["command"] == "pause"
    assert call_args[0][1]["$set"]["reason"] == "Maintenance"
    assert call_args[0][1]["$set"]["updated_by"] == "ops_team"

    assert result == updated_doc


@pytest.mark.asyncio
async def test_set_global_command_validates_input(mock_mongo_client):
    """Test setting global command validates command input"""
    client, db, collection = mock_mongo_client

    coordinator = DistributedControlCoordinator(
        mongo_client=client,
        db_name="test_db"
    )

    with pytest.raises(ValueError, match="Invalid command"):
        await coordinator.set_global_command(command="invalid_command")


@pytest.mark.asyncio
async def test_get_current_command(mock_mongo_client):
    """Test getting current command"""
    client, db, collection = mock_mongo_client

    current_doc = {
        "_id": "global_control",
        "command": "running",
        "version": 5,
        "timestamp": datetime.utcnow()
    }

    collection.find_one.return_value = current_doc

    coordinator = DistributedControlCoordinator(
        mongo_client=client,
        db_name="test_db"
    )

    result = await coordinator.get_current_command()

    collection.find_one.assert_called_once_with({"_id": "global_control"})
    assert result == current_doc


@pytest.mark.asyncio
async def test_polling_watch_detects_changes(mock_mongo_client):
    """Test polling watch detects version changes"""
    client, db, collection = mock_mongo_client

    # Simulate version changing from 1 to 2
    collection.find_one.side_effect = [
        {"_id": "global_control", "command": "running", "version": 1},
        {"_id": "global_control", "command": "pause", "version": 2},
    ]

    coordinator = DistributedControlCoordinator(
        mongo_client=client,
        db_name="test_db",
        polling_interval=0.1  # Fast polling for testing
    )
    coordinator._last_version = 1

    callback_called = asyncio.Event()
    received_command = None
    received_doc = None

    async def callback(command, doc):
        nonlocal received_command, received_doc
        received_command = command
        received_doc = doc
        callback_called.set()

    # Run polling watch in background
    watch_task = asyncio.create_task(
        coordinator._watch_with_polling(callback)
    )

    # Wait for callback to be called (with timeout)
    try:
        await asyncio.wait_for(callback_called.wait(), timeout=1.0)
    finally:
        watch_task.cancel()
        try:
            await watch_task
        except asyncio.CancelledError:
            pass

    assert received_command == "pause"
    assert received_doc["version"] == 2


@pytest.mark.asyncio
async def test_polling_watch_ignores_same_version(mock_mongo_client):
    """Test polling watch ignores documents with same version"""
    client, db, collection = mock_mongo_client

    # Same version returned multiple times
    collection.find_one.return_value = {
        "_id": "global_control",
        "command": "running",
        "version": 1
    }

    coordinator = DistributedControlCoordinator(
        mongo_client=client,
        db_name="test_db",
        polling_interval=0.05
    )
    coordinator._last_version = 1

    callback_count = 0

    async def callback(command, doc):
        nonlocal callback_count
        callback_count += 1

    # Run polling for a short time
    watch_task = asyncio.create_task(
        coordinator._watch_with_polling(callback)
    )

    await asyncio.sleep(0.3)

    watch_task.cancel()
    try:
        await watch_task
    except asyncio.CancelledError:
        pass

    # Callback should NOT be called since version didn't change
    assert callback_count == 0


@pytest.mark.asyncio
async def test_start_and_stop_watching(mock_mongo_client):
    """Test starting and stopping watch task"""
    client, db, collection = mock_mongo_client

    collection.find_one.return_value = {
        "_id": "global_control",
        "command": "running",
        "version": 1
    }

    coordinator = DistributedControlCoordinator(
        mongo_client=client,
        db_name="test_db",
        enable_change_streams=False  # Force polling mode
    )
    coordinator._last_version = 0

    async def callback(command, doc):
        pass

    # Start watching
    task = coordinator.start_watching(callback)
    assert task is not None
    assert not task.done()

    # Give it a moment to start
    await asyncio.sleep(0.1)

    # Stop watching
    await coordinator.stop_watching()

    # Task should be cancelled
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_get_stats(mock_mongo_client):
    """Test getting distributed control stats"""
    client, db, collection = mock_mongo_client

    current_doc = {
        "_id": "global_control",
        "command": "pause",
        "version": 10,
        "timestamp": datetime.utcnow(),
        "reason": "Scheduled maintenance",
        "updated_by": "cronjob"
    }

    collection.find_one.return_value = current_doc

    coordinator = DistributedControlCoordinator(
        mongo_client=client,
        db_name="test_db",
        polling_interval=15
    )
    coordinator._watch_mode = "polling"

    stats = await coordinator.get_stats()

    assert stats["watch_mode"] == "polling"
    assert stats["polling_interval"] == 15
    assert stats["current_command"] == "pause"
    assert stats["current_version"] == 10
    assert stats["updated_by"] == "cronjob"
    assert stats["reason"] == "Scheduled maintenance"


@pytest.mark.asyncio
async def test_watch_mode_tracking():
    """Test watch mode is properly tracked"""
    client = AsyncMock(spec=AsyncIOMotorClient)
    db = AsyncMock()
    collection = AsyncMock()

    client.__getitem__.return_value = db
    db.__getitem__.return_value = collection

    coordinator = DistributedControlCoordinator(
        mongo_client=client,
        db_name="test_db"
    )

    # Initially None
    assert coordinator.get_watch_mode() is None

    # Set to polling
    coordinator._watch_mode = "polling"
    assert coordinator.get_watch_mode() == "polling"

    # Set to change_streams
    coordinator._watch_mode = "change_streams"
    assert coordinator.get_watch_mode() == "change_streams"


@pytest.mark.asyncio
async def test_callback_receives_all_document_fields(mock_mongo_client):
    """Test callback receives complete document with all fields"""
    client, db, collection = mock_mongo_client

    full_doc = {
        "_id": "global_control",
        "command": "shutdown",
        "version": 100,
        "timestamp": datetime.utcnow(),
        "reason": "Emergency shutdown",
        "updated_by": "admin"
    }

    collection.find_one.side_effect = [
        {"_id": "global_control", "command": "running", "version": 99},
        full_doc,
    ]

    coordinator = DistributedControlCoordinator(
        mongo_client=client,
        db_name="test_db",
        polling_interval=0.05
    )
    coordinator._last_version = 99

    received_doc = None
    callback_called = asyncio.Event()

    async def callback(command, doc):
        nonlocal received_doc
        received_doc = doc
        callback_called.set()

    watch_task = asyncio.create_task(
        coordinator._watch_with_polling(callback)
    )

    try:
        await asyncio.wait_for(callback_called.wait(), timeout=1.0)
    finally:
        watch_task.cancel()
        try:
            await watch_task
        except asyncio.CancelledError:
            pass

    assert received_doc is not None
    assert received_doc["command"] == "shutdown"
    assert received_doc["version"] == 100
    assert received_doc["reason"] == "Emergency shutdown"
    assert received_doc["updated_by"] == "admin"


@pytest.mark.asyncio
async def test_multiple_command_changes(mock_mongo_client):
    """Test handling multiple command changes in sequence"""
    client, db, collection = mock_mongo_client

    # Simulate sequence of commands
    docs = [
        {"_id": "global_control", "command": "running", "version": 1},
        {"_id": "global_control", "command": "pause", "version": 2},
        {"_id": "global_control", "command": "running", "version": 3},
        {"_id": "global_control", "command": "shutdown", "version": 4},
    ]

    collection.find_one.side_effect = docs

    coordinator = DistributedControlCoordinator(
        mongo_client=client,
        db_name="test_db",
        polling_interval=0.05
    )
    coordinator._last_version = 1

    received_commands = []
    expected_count = 3  # versions 2, 3, 4
    event = asyncio.Event()

    async def callback(command, doc):
        received_commands.append((command, doc["version"]))
        if len(received_commands) >= expected_count:
            event.set()

    watch_task = asyncio.create_task(
        coordinator._watch_with_polling(callback)
    )

    try:
        await asyncio.wait_for(event.wait(), timeout=2.0)
    finally:
        watch_task.cancel()
        try:
            await watch_task
        except asyncio.CancelledError:
            pass

    assert len(received_commands) == 3
    assert received_commands[0] == ("pause", 2)
    assert received_commands[1] == ("running", 3)
    assert received_commands[2] == ("shutdown", 4)
