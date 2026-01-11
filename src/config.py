"""
Configuration management for the pulling agent.
"""
import os
from dataclasses import dataclass
from enum import Enum


class AgentState(Enum):
    """Agent operational states"""
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass
class AgentConfig:
    """Configuration for the pulling agent"""
    
    # MongoDB settings
    mongodb_uri: str
    mongodb_database: str
    mongodb_collection: str
    
    # Polling settings
    poll_interval: int = 5  # seconds between poll cycles
    batch_size: int = 100   # documents to process per batch
    
    # Operational settings
    shutdown_timeout: int = 30      # seconds for graceful shutdown
    heartbeat_interval: int = 5     # seconds between heartbeat updates
    max_retries: int = 3            # max retries for failed operations

    # Distributed control settings
    enable_distributed_control: bool = True     # Enable distributed control coordination
    enable_change_streams: bool = True          # Try Change Streams first (auto-fallback to polling)
    control_polling_interval: int = 10          # seconds between polls (polling mode only)

    # Logging
    log_level: str = "INFO"
    
    @classmethod
    def from_env(cls) -> "AgentConfig":
        """Load configuration from environment variables"""
        return cls(
            mongodb_uri=os.getenv("MONGODB_URI", ""),
            mongodb_database=os.getenv("MONGODB_DATABASE", ""),
            mongodb_collection=os.getenv("MONGODB_COLLECTION", ""),
            poll_interval=int(os.getenv("POLL_INTERVAL", "5")),
            batch_size=int(os.getenv("BATCH_SIZE", "100")),
            shutdown_timeout=int(os.getenv("SHUTDOWN_TIMEOUT", "30")),
            heartbeat_interval=int(os.getenv("HEARTBEAT_INTERVAL", "5")),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            enable_distributed_control=os.getenv("ENABLE_DISTRIBUTED_CONTROL", "true").lower() == "true",
            enable_change_streams=os.getenv("ENABLE_CHANGE_STREAMS", "true").lower() == "true",
            control_polling_interval=int(os.getenv("CONTROL_POLLING_INTERVAL", "10")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
    
    def validate(self) -> None:
        """Validate configuration"""
        if not self.mongodb_uri:
            raise ValueError("MONGODB_URI is required")
        if not self.mongodb_database:
            raise ValueError("MONGODB_DATABASE is required")
        if not self.mongodb_collection:
            raise ValueError("MONGODB_COLLECTION is required")
        
        if self.poll_interval < 1:
            raise ValueError("POLL_INTERVAL must be >= 1")
        if self.batch_size < 1:
            raise ValueError("BATCH_SIZE must be >= 1")
        if self.shutdown_timeout < 1:
            raise ValueError("SHUTDOWN_TIMEOUT must be >= 1")
        if self.control_polling_interval < 1:
            raise ValueError("CONTROL_POLLING_INTERVAL must be >= 1")
