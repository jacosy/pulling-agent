"""
Unit tests for the pulling agent.
"""
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.agent import PullingAgent
from src.config import AgentConfig, AgentState
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
    manager.connect = AsyncMock()
    manager.close = AsyncMock()
    manager.is_connected = True
    manager.collection = MagicMock()
    return manager


@pytest.fixture
def agent(config, mongo_manager):
    """Create agent instance for testing"""
    # Mock signal handler setup to avoid issues in tests
    with patch('signal.signal'):
        agent = PullingAgent(config, mongo_manager)
        # Override health directories for testing
        agent.health_dir = Path("/tmp/test_health")
        agent.health_dir.mkdir(exist_ok=True)
        agent.liveness_file = agent.health_dir / "liveness"
        agent.readiness_file = agent.health_dir / "readiness"
        agent.control_file = Path("/tmp/test_control/state")
        agent.control_file.parent.mkdir(exist_ok=True)

        yield agent

        # Cleanup
        if agent.liveness_file.exists():
            agent.liveness_file.unlink()
        if agent.readiness_file.exists():
            agent.readiness_file.unlink()
        if agent.control_file.exists():
            agent.control_file.unlink()


class TestAgentConfig:
    """Tests for AgentConfig"""
    
    def test_config_validation_success(self, config):
        """Test valid configuration"""
        config.validate()  # Should not raise
    
    def test_config_validation_missing_uri(self):
        """Test validation fails with missing URI"""
        config = AgentConfig(
            mongodb_uri="",
            mongodb_database="testdb",
            mongodb_collection="testcollection"
        )
        with pytest.raises(ValueError, match="MONGODB_URI is required"):
            config.validate()
    
    def test_config_from_env(self):
        """Test loading config from environment"""
        with patch.dict('os.environ', {
            'MONGODB_URI': 'mongodb://test:27017',
            'MONGODB_DATABASE': 'testdb',
            'MONGODB_COLLECTION': 'testcoll',
            'POLL_INTERVAL': '10',
            'BATCH_SIZE': '50'
        }):
            config = AgentConfig.from_env()
            assert config.mongodb_uri == 'mongodb://test:27017'
            assert config.poll_interval == 10
            assert config.batch_size == 50


class TestPullingAgent:
    """Tests for PullingAgent"""
    
    @pytest.mark.asyncio
    async def test_agent_initialization(self, agent):
        """Test agent initializes correctly"""
        assert agent.state == AgentState.RUNNING
        assert not agent._shutdown_event.is_set()
        assert agent._pause_event.is_set()
    
    @pytest.mark.asyncio
    async def test_pause_resume(self, agent):
        """Test pause and resume functionality"""
        assert agent.state == AgentState.RUNNING
        assert agent._pause_event.is_set()
        
        # Pause
        agent.pause()
        assert agent.state == AgentState.PAUSED
        assert not agent._pause_event.is_set()
        assert not agent.readiness_file.exists()
        
        # Resume
        agent.resume()
        assert agent.state == AgentState.RUNNING
        assert agent._pause_event.is_set()
    
    @pytest.mark.asyncio
    async def test_shutdown(self, agent):
        """Test graceful shutdown"""
        await agent.shutdown()
        assert agent.state == AgentState.STOPPING
        assert agent._shutdown_event.is_set()
    
    @pytest.mark.asyncio
    async def test_liveness_file_update(self, agent):
        """Test liveness file is created and updated"""
        agent._update_liveness(healthy=True)
        assert agent.liveness_file.exists()
        
        content = agent.liveness_file.read_text()
        assert "running" in content
        
        agent._update_liveness(healthy=False)
        assert not agent.liveness_file.exists()
    
    @pytest.mark.asyncio
    async def test_readiness_file_update(self, agent):
        """Test readiness file is created when ready"""
        agent._update_readiness(ready=True)
        assert agent.readiness_file.exists()
        
        agent._update_readiness(ready=False)
        assert not agent.readiness_file.exists()
    
    @pytest.mark.asyncio
    async def test_process_batch_called(self, agent):
        """Test that worker.process_batch is called during run"""
        # Mock worker.process_batch
        agent.worker.process_batch = AsyncMock()

        # Create a task that will shutdown after short delay
        async def delayed_shutdown():
            await asyncio.sleep(0.1)
            await agent.shutdown()

        # Run agent with auto-shutdown
        await asyncio.gather(
            agent.run(),
            delayed_shutdown()
        )

        # Verify worker.process_batch was called
        assert agent.worker.process_batch.called
        assert agent.mongo.connect.called
        assert agent.mongo.close.called


class TestMongoClientManager:
    """Tests for MongoClientManager"""
    
    @pytest.mark.asyncio
    async def test_connection_lifecycle(self):
        """Test MongoDB connection lifecycle"""
        with patch('src.mongo_client.AsyncIOMotorClient') as mock_client:
            # Setup mock
            mock_instance = MagicMock()
            mock_instance.admin.command = AsyncMock(return_value={"ok": 1})
            mock_client.return_value = mock_instance
            
            manager = MongoClientManager(
                uri="mongodb://localhost:27017",
                database="testdb",
                collection="testcoll"
            )
            
            # Test connect
            await manager.connect()
            assert manager.is_connected
            mock_instance.admin.command.assert_called_once_with('ping')
            
            # Test close
            await manager.close()
            assert not manager.is_connected
            mock_instance.close.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
