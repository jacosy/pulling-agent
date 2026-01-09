#!/usr/bin/env python3
"""
Test script to verify supervisor crash recovery functionality.

This script simulates component crashes and verifies that:
1. Components restart automatically after crashes
2. Exponential backoff is applied between restarts
3. Maximum restart limits are enforced
4. Both components can run independently
"""
import asyncio
import logging
import sys
from datetime import datetime

# Add src to path
sys.path.insert(0, '/home/user/pulling-agent/src')

from supervisor import Supervisor, SupervisedComponent, ComponentState

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CrashingComponent:
    """Component that crashes after a specified number of iterations"""

    def __init__(self, name: str, crash_after: int = 3, total_iterations: int = 10):
        self.name = name
        self.crash_after = crash_after
        self.total_iterations = total_iterations
        self.iteration = 0
        self.crash_count = 0

    async def run(self):
        """Run the component, crashing after specified iterations"""
        logger.info(f"[{self.name}] Starting (crash_count={self.crash_count})")

        while self.iteration < self.total_iterations:
            self.iteration += 1
            logger.info(f"[{self.name}] Iteration {self.iteration}/{self.total_iterations}")

            # Simulate work
            await asyncio.sleep(0.5)

            # Crash after specified iterations
            if self.iteration >= self.crash_after:
                self.crash_count += 1
                self.iteration = 0  # Reset for next restart
                logger.error(f"[{self.name}] CRASH! (crash #{self.crash_count})")
                raise RuntimeError(f"{self.name} intentional crash #{self.crash_count}")

        logger.info(f"[{self.name}] Completed successfully!")


async def test_basic_restart():
    """Test 1: Basic crash and restart functionality"""
    logger.info("\n=== TEST 1: Basic Crash and Restart ===")

    component = CrashingComponent("test-component", crash_after=2, total_iterations=6)

    supervised = SupervisedComponent(
        name="test-component",
        component_func=component.run,
        max_restarts=5,
        initial_backoff=0.5,
        max_backoff=2.0
    )

    await supervised.start()

    # Wait a bit for it to run and crash/restart
    await asyncio.sleep(8)

    # Stop the component
    await supervised.stop()

    stats = supervised.get_stats()
    logger.info(f"Stats: {stats}")

    # Verify it crashed and restarted
    assert stats['crash_count'] > 0, "Component should have crashed at least once"
    assert stats['restart_count'] > 0, "Component should have restarted at least once"

    logger.info("✓ TEST 1 PASSED")


async def test_max_restarts():
    """Test 2: Maximum restart limit enforcement"""
    logger.info("\n=== TEST 2: Maximum Restart Limit ===")

    # Component that always crashes
    async def always_crash():
        await asyncio.sleep(0.1)
        raise RuntimeError("Always crashes")

    supervised = SupervisedComponent(
        name="always-crash",
        component_func=always_crash,
        max_restarts=3,
        initial_backoff=0.1,
        max_backoff=0.5
    )

    await supervised.start()

    # Wait for it to exceed max restarts
    try:
        await supervised.wait()
    except RuntimeError as e:
        logger.info(f"Component failed as expected: {e}")

    stats = supervised.get_stats()
    logger.info(f"Stats: {stats}")

    # Verify it stopped after max restarts
    assert stats['restart_count'] == 3, f"Should have exactly 3 restarts, got {stats['restart_count']}"
    assert stats['crash_count'] == 4, f"Should have 4 crashes (initial + 3 restarts), got {stats['crash_count']}"
    assert stats['state'] == 'stopped', f"Should be stopped, got {stats['state']}"

    logger.info("✓ TEST 2 PASSED")


async def test_supervisor_multiple_components():
    """Test 3: Supervisor managing multiple components"""
    logger.info("\n=== TEST 3: Multiple Components ===")

    supervisor = Supervisor()

    # Add two components with different crash patterns
    comp1 = CrashingComponent("comp1", crash_after=2, total_iterations=4)
    comp2 = CrashingComponent("comp2", crash_after=3, total_iterations=6)

    supervisor.add_component(
        name="comp1",
        component_func=comp1.run,
        max_restarts=3,
        max_backoff=1.0
    )

    supervisor.add_component(
        name="comp2",
        component_func=comp2.run,
        max_restarts=3,
        max_backoff=1.0
    )

    await supervisor.start_all()

    # Run for a bit
    await asyncio.sleep(10)

    # Stop all
    await supervisor.stop_all()

    stats = supervisor.get_all_stats()
    logger.info(f"All stats: {stats}")

    # Verify both components ran
    assert 'comp1' in stats, "comp1 should be in stats"
    assert 'comp2' in stats, "comp2 should be in stats"
    assert stats['comp1']['crash_count'] > 0, "comp1 should have crashed"
    assert stats['comp2']['crash_count'] > 0, "comp2 should have crashed"

    logger.info("✓ TEST 3 PASSED")


async def test_graceful_component():
    """Test 4: Component that completes successfully without crashing"""
    logger.info("\n=== TEST 4: Graceful Completion ===")

    async def successful_component():
        """Component that completes successfully"""
        for i in range(3):
            logger.info(f"Working... {i+1}/3")
            await asyncio.sleep(0.3)
        logger.info("Completed successfully!")

    supervised = SupervisedComponent(
        name="successful",
        component_func=successful_component,
        max_restarts=3
    )

    await supervised.start()
    await supervised.wait()

    stats = supervised.get_stats()
    logger.info(f"Stats: {stats}")

    # Verify it completed without crashes
    assert stats['crash_count'] == 0, "Should have no crashes"
    assert stats['restart_count'] == 0, "Should have no restarts"
    assert stats['state'] == 'stopped', "Should be stopped"

    logger.info("✓ TEST 4 PASSED")


async def main():
    """Run all tests"""
    logger.info("Starting supervisor tests...")

    try:
        await test_basic_restart()
        await test_max_restarts()
        await test_supervisor_multiple_components()
        await test_graceful_component()

        logger.info("\n" + "="*50)
        logger.info("ALL TESTS PASSED! ✓")
        logger.info("="*50)

    except AssertionError as e:
        logger.error(f"\nTEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\nTEST ERROR: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
