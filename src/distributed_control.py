"""
Distributed Control Coordinator for Multi-Agent Systems

Provides two methods for coordinating control commands across multiple agents:
1. MongoDB Change Streams (recommended, event-driven, requires replica set)
2. Polling fallback (for single-node MongoDB, configurable interval)

The coordinator automatically detects which method to use based on MongoDB deployment.
"""

from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from pymongo.errors import PyMongoError, OperationFailure
import asyncio
from typing import Callable, Optional, Awaitable
import logging

logger = logging.getLogger(__name__)


class DistributedControlCoordinator:
    """
    Coordinates agent control across multiple instances.

    Supports two watch modes:
    - Change Streams: Event-driven, real-time (requires MongoDB replica set)
    - Polling: Periodic checks, configurable interval (works with single-node)

    The coordinator auto-detects the best available method.
    """

    def __init__(
        self,
        mongo_client: AsyncIOMotorClient,
        db_name: str,
        polling_interval: int = 10,
        enable_change_streams: bool = True
    ):
        """
        Initialize distributed control coordinator.

        Args:
            mongo_client: Motor async MongoDB client
            db_name: Database name
            polling_interval: Seconds between polls (fallback mode only)
            enable_change_streams: Try Change Streams first (auto-fallback to polling)
        """
        self.db = mongo_client[db_name]
        self.control_collection = self.db["agent_control"]
        self.polling_interval = polling_interval
        self.enable_change_streams = enable_change_streams
        self._watch_task: Optional[asyncio.Task] = None
        self._watch_mode: Optional[str] = None  # "change_streams" or "polling"
        self._last_version: int = 0

    async def initialize(self) -> None:
        """
        Initialize the control collection with default state.
        Creates the global control document if it doesn't exist.
        """
        # Create index for version tracking
        await self.control_collection.create_index("version")

        # Initialize with default state if not exists
        existing = await self.control_collection.find_one({"_id": "global_control"})
        if not existing:
            await self.control_collection.insert_one({
                "_id": "global_control",
                "command": "running",
                "version": 1,
                "timestamp": datetime.utcnow(),
                "reason": "Initial state",
                "updated_by": "system"
            })
            logger.info("Initialized global control document")
            self._last_version = 1
        else:
            logger.info(
                f"Found existing control document: "
                f"command={existing['command']}, version={existing['version']}"
            )
            self._last_version = existing['version']

    async def set_global_command(
        self,
        command: str,
        reason: str = "",
        updated_by: str = "api"
    ) -> dict:
        """
        Set command for all agents in the cluster.

        Args:
            command: One of "running", "pause", "shutdown"
            reason: Human-readable reason for the change
            updated_by: Who/what triggered this change (for audit)

        Returns:
            Updated document with new version

        Raises:
            ValueError: If command is invalid
        """
        valid_commands = {"running", "pause", "shutdown"}
        if command not in valid_commands:
            raise ValueError(
                f"Invalid command '{command}'. Must be one of {valid_commands}"
            )

        result = await self.control_collection.find_one_and_update(
            {"_id": "global_control"},
            {
                "$inc": {"version": 1},
                "$set": {
                    "command": command,
                    "timestamp": datetime.utcnow(),
                    "reason": reason,
                    "updated_by": updated_by
                }
            },
            return_document=True
        )

        if result:
            logger.info(
                f"Global command set: {command} (version {result['version']}) "
                f"by {updated_by} - {reason}"
            )
        else:
            logger.error("Failed to set global command: document not found")

        return result

    async def get_current_command(self) -> Optional[dict]:
        """
        Get current global command state.

        Returns:
            Control document or None if not initialized
        """
        doc = await self.control_collection.find_one({"_id": "global_control"})
        return doc

    async def _check_change_streams_support(self) -> bool:
        """
        Check if MongoDB deployment supports Change Streams.
        Requires MongoDB 3.6+ and replica set deployment.

        Returns:
            True if Change Streams are supported, False otherwise
        """
        try:
            # Try to create a change stream (will fail on single-node)
            async with self.control_collection.watch([]) as stream:
                # If we get here, change streams are supported
                logger.info("✓ MongoDB Change Streams are supported")
                return True
        except OperationFailure as e:
            # Error 40573 = "The $changeStream stage is only supported on replica sets"
            if e.code == 40573:
                logger.warning(
                    "MongoDB Change Streams not available: "
                    "Replica set required. Using polling fallback."
                )
            else:
                logger.warning(f"MongoDB Change Streams check failed: {e}")
            return False
        except Exception as e:
            logger.warning(f"Unexpected error checking Change Streams support: {e}")
            return False

    async def _watch_with_change_streams(
        self,
        callback: Callable[[str, dict], Awaitable[None]]
    ) -> None:
        """
        Watch for control changes using MongoDB Change Streams (event-driven).
        This method blocks indefinitely and only returns on cancellation.

        Args:
            callback: Async function called when command changes
                     callback(command: str, full_document: dict)
        """
        logger.info("Starting MongoDB Change Stream watch on agent_control collection")

        # Pipeline to filter only updates to the global_control document
        pipeline = [
            {
                "$match": {
                    "operationType": {"$in": ["insert", "update", "replace"]},
                    "fullDocument._id": "global_control"
                }
            }
        ]

        retry_delay = 1  # Start with 1 second retry
        max_retry_delay = 30  # Max 30 seconds between retries

        while True:
            try:
                # Open change stream with full document lookup
                async with self.control_collection.watch(
                    pipeline=pipeline,
                    full_document="updateLookup"  # Get full document, not just changes
                ) as change_stream:

                    logger.info("✓ Change stream connected successfully (event-driven mode)")
                    retry_delay = 1  # Reset retry delay on successful connection

                    # Wait for changes (this blocks until a change occurs)
                    async for change in change_stream:
                        try:
                            full_doc = change["fullDocument"]
                            command = full_doc["command"]
                            version = full_doc["version"]
                            reason = full_doc.get("reason", "")
                            updated_by = full_doc.get("updated_by", "unknown")

                            logger.info(
                                f"[Change Stream] Received command: {command} "
                                f"(v{version}) - {reason} [by {updated_by}]"
                            )

                            # Execute callback
                            await callback(command, full_doc)

                        except Exception as e:
                            logger.error(
                                f"Error processing change event: {e}",
                                exc_info=True
                            )

            except PyMongoError as e:
                logger.error(
                    f"MongoDB change stream error: {e}. "
                    f"Retrying in {retry_delay}s..."
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)  # Exponential backoff

            except asyncio.CancelledError:
                logger.info("Change stream watch cancelled")
                break

            except Exception as e:
                logger.error(
                    f"Unexpected error in change stream: {e}",
                    exc_info=True
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

    async def _watch_with_polling(
        self,
        callback: Callable[[str, dict], Awaitable[None]]
    ) -> None:
        """
        Watch for control changes using polling (fallback method).
        Polls MongoDB every polling_interval seconds.

        Args:
            callback: Async function called when command changes
                     callback(command: str, full_document: dict)
        """
        logger.info(
            f"Starting polling watch on agent_control collection "
            f"(interval: {self.polling_interval}s)"
        )

        retry_delay = 1
        max_retry_delay = 30

        while True:
            try:
                current = await self.get_current_command()

                if current and current["version"] > self._last_version:
                    # Version changed - new command detected
                    self._last_version = current["version"]
                    command = current["command"]
                    reason = current.get("reason", "")
                    updated_by = current.get("updated_by", "unknown")

                    logger.info(
                        f"[Polling] Detected command change: {command} "
                        f"(v{current['version']}) - {reason} [by {updated_by}]"
                    )

                    # Execute callback
                    await callback(command, current)

                    retry_delay = 1  # Reset on success

                # Wait for next poll
                await asyncio.sleep(self.polling_interval)

            except PyMongoError as e:
                logger.error(
                    f"MongoDB polling error: {e}. "
                    f"Retrying in {retry_delay}s..."
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

            except asyncio.CancelledError:
                logger.info("Polling watch cancelled")
                break

            except Exception as e:
                logger.error(
                    f"Unexpected error in polling watch: {e}",
                    exc_info=True
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

    async def watch_for_changes(
        self,
        callback: Callable[[str, dict], Awaitable[None]]
    ) -> None:
        """
        Watch for control changes using the best available method.
        Automatically selects Change Streams or polling based on MongoDB deployment.

        Args:
            callback: Async function called when command changes
                     callback(command: str, full_document: dict)
        """
        # Determine which watch mode to use
        if self.enable_change_streams:
            change_streams_supported = await self._check_change_streams_support()

            if change_streams_supported:
                self._watch_mode = "change_streams"
                logger.info("Using MongoDB Change Streams (event-driven, real-time)")
                await self._watch_with_change_streams(callback)
            else:
                self._watch_mode = "polling"
                logger.info(
                    f"Using polling fallback (interval: {self.polling_interval}s)"
                )
                await self._watch_with_polling(callback)
        else:
            self._watch_mode = "polling"
            logger.info(
                f"Change Streams disabled. Using polling (interval: {self.polling_interval}s)"
            )
            await self._watch_with_polling(callback)

    def start_watching(
        self,
        callback: Callable[[str, dict], Awaitable[None]]
    ) -> asyncio.Task:
        """
        Start watching for changes in a background task.
        Automatically selects the best watch method (Change Streams or polling).

        Args:
            callback: Async function called when command changes

        Returns:
            The background task (can be cancelled later)
        """
        if self._watch_task and not self._watch_task.done():
            logger.warning("Watch task already running")
            return self._watch_task

        self._watch_task = asyncio.create_task(self.watch_for_changes(callback))
        return self._watch_task

    async def stop_watching(self) -> None:
        """Stop watching for changes and cleanup resources."""
        if self._watch_task and not self._watch_task.done():
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass
            logger.info(f"Stopped watching for control changes (mode: {self._watch_mode})")
            self._watch_task = None

    def get_watch_mode(self) -> Optional[str]:
        """
        Get the current watch mode.

        Returns:
            "change_streams", "polling", or None if not started
        """
        return self._watch_mode

    async def get_stats(self) -> dict:
        """
        Get statistics about the distributed control system.

        Returns:
            Dictionary with control state and metadata
        """
        current = await self.get_current_command()

        return {
            "watch_mode": self._watch_mode,
            "polling_interval": self.polling_interval if self._watch_mode == "polling" else None,
            "current_command": current["command"] if current else None,
            "current_version": current["version"] if current else None,
            "last_updated": current["timestamp"].isoformat() if current else None,
            "updated_by": current.get("updated_by") if current else None,
            "reason": current.get("reason") if current else None,
        }
