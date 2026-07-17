"""Test suite for the chaos engineering framework.

Verifies that fault-injection primitives behave correctly:
- failures fire deterministically when probability is 1.0
- failures are skipped when probability is 0.0
- count-limited failures stop firing after n calls
- patch restores the original on context exit
- nested contexts stack correctly
"""

from __future__ import annotations

import pytest

from tests.chaos.chaos_tools import (
    FaultRecipe,
    REGISTRY,
    fault_inject,
)


class FakeMT5Bridge:
    """Stub bridge for fault-injection tests."""

    def __init__(self) -> None:
        self.call_count = 0

    def fetch_ohlcv(self, symbol: str, years: int = 2) -> dict:
        self.call_count += 1
        return {"symbol": symbol, "years": years, "data": []}

    def get_account(self) -> dict:
        return {"balance": 100000}


class TestFaultRecipe:
    def test_default_recipe_attributes(self):
        r = FaultRecipe(name="test", description="d")
        assert r.n_failures == 1
        assert r.fail_probability == 1.0
        assert r.exception is None
        assert r.delay_seconds == 0.0

    def test_recipe_attributes_can_be_overridden(self):
        r = FaultRecipe(
            name="x",
            description="d",
            n_failures=3,
            fail_probability=0.5,
            delay_seconds=0.01,
        )
        assert r.n_failures == 3
        assert r.fail_probability == 0.5
        assert r.delay_seconds == 0.01


class TestFaultInjectContextManager:
    def test_replaces_method_during_context(self):
        bridge = FakeMT5Bridge()
        recipe = FaultRecipe(
            name="always_fail",
            description="always fails",
            exception=RuntimeError,
        )
        # Verify the original raised nothing
        orig_result = bridge.fetch_ohlcv("EURUSD")
        assert orig_result["symbol"] == "EURUSD"

        with fault_inject(bridge, "fetch_ohlcv", recipe) as patched:
            assert bridge.fetch_ohlcv is not None
            with pytest.raises(RuntimeError):
                bridge.fetch_ohlcv("EURUSD")
        # Restored on exit — original behavior returns
        result = bridge.fetch_ohlcv("EURUSD")
        assert result["symbol"] == "EURUSD"

    def test_n_failures_limited(self):
        bridge = FakeMT5Bridge()
        recipe = FaultRecipe(
            name="fail_twice",
            description="fails twice",
            exception=RuntimeError,
            n_failures=2,
        )
        with fault_inject(bridge, "fetch_ohlcv", recipe):
            with pytest.raises(RuntimeError):
                bridge.fetch_ohlcv("EURUSD")
            with pytest.raises(RuntimeError):
                bridge.fetch_ohlcv("EURUSD")
            # Third call should pass through
            result = bridge.fetch_ohlcv("EURUSD")
            assert result["symbol"] == "EURUSD"
            assert bridge.call_count == 1

    def test_fail_probability_zero_means_no_failures(self):
        """Probability zero disables the fault entirely."""
        bridge = FakeMT5Bridge()
        recipe = FaultRecipe(
            name="p_zero",
            description="always passes",
            fail_probability=0.0,
        )
        with fault_inject(bridge, "fetch_ohlcv", recipe):
            result = bridge.fetch_ohlcv("EURUSD")
        assert result["symbol"] == "EURUSD"

    def test_probability_one_means_always_fails(self):
        bridge = FakeMT5Bridge()
        recipe = FaultRecipe(
            name="p_one",
            description="always fails",
            fail_probability=1.0,
            n_failures=100,  # effectively infinite
        )
        with fault_inject(bridge, "fetch_ohlcv", recipe):
            for _ in range(5):
                with pytest.raises(RuntimeError):
                    bridge.fetch_ohlcv("EURUSD")
        # Original never gets called
        assert bridge.call_count == 0

    def test_non_callable_attribute_rejected(self):
        with pytest.raises(TypeError):
            with fault_inject(object(), "__class__", FaultRecipe(name="x", description="y")):
                pass

    def test_restoration_on_exception(self):
        bridge = FakeMT5Bridge()
        recipe = FaultRecipe(
            name="explode",
            description="explode",
            exception=RuntimeError,
        )
        with pytest.raises(ValueError):
            with fault_inject(bridge, "fetch_ohlcv", recipe):
                raise ValueError("inner exception")
        # Even after exception, original behavior is restored
        result = bridge.fetch_ohlcv("EURUSD")
        assert result["symbol"] == "EURUSD"

    def test_nested_context_stacking(self):
        bridge = FakeMT5Bridge()
        # Establish baseline behavior
        baseline_result = bridge.fetch_ohlcv("EURUSD")
        assert baseline_result["symbol"] == "EURUSD"

        r1 = FaultRecipe(
            name="r1",
            description="once",
            exception=RuntimeError,
            n_failures=1,
        )
        r2 = FaultRecipe(
            name="r2",
            description="thrice",
            exception=RuntimeError,
            n_failures=3,
        )
        with fault_inject(bridge, "fetch_ohlcv", r1):
            with fault_inject(bridge, "fetch_ohlcv", r2):
                # Now we are double-patched — both should fail
                for _ in range(3):
                    with pytest.raises(RuntimeError):
                        bridge.fetch_ohlcv("EURUSD")
            # r1 still in effect after leaving the inner context
            with pytest.raises(RuntimeError):
                bridge.fetch_ohlcv("EURUSD")
            # r1 has burned its single failure → pass through next
            result = bridge.fetch_ohlcv("EURUSD")
            assert result["symbol"] == "EURUSD"
        # Back to baseline
        result = bridge.fetch_ohlcv("EURUSD")
        assert result["symbol"] == "EURUSD"

    def test_attempt_to_patch_missing_attr_raises(self):
        class Empty:
            pass

        empty = Empty()
        # Should fail with AttributeError on the getattr fallback
        recipe = FaultRecipe(name="x", description="y")
        # Note: getattr raises AttributeError before we check callability
        # So this should propagate
        with pytest.raises(AttributeError):
            with fault_inject(empty, "nonexistent", recipe):
                pass


class TestChaosRegistry:
    def test_recipes_registered(self):
        before = len(REGISTRY.list_scenarios())
        bridge = FakeMT5Bridge()
        recipe = FaultRecipe(name="r1", description="d1")
        with fault_inject(bridge, "fetch_ohlcv", recipe):
            pass
        assert len(REGISTRY.list_scenarios()) == before + 1
        assert recipe in REGISTRY.list_scenarios()


class TestChaosScenarios:
    """Realistic scenarios used in property-based chaos testing."""

    def test_transient_bridge_disconnect(self):
        """Simulate one bridge disconnect that recovers after a single retry."""
        bridge = FakeMT5Bridge()
        recipe = FaultRecipe(
            name="disconnect_once",
            description="simulates one transient disconnect",
            exception=ConnectionError,
            n_failures=1,
        )
        retries = 0
        with fault_inject(bridge, "fetch_ohlcv", recipe):
            try:
                bridge.fetch_ohlcv("EURUSD")
            except ConnectionError:
                retries += 1
                # Recovery: second call should succeed
                result = bridge.fetch_ohlcv("EURUSD")
                assert result["symbol"] == "EURUSD"
        assert retries == 1

    def test_persistent_bridge_disconnect_safety(self):
        """When the fault persists, the calling code must give up cleanly."""
        bridge = FakeMT5Bridge()
        recipe = FaultRecipe(
            name="permanent_disconnect",
            description="simulates permanent disconnect",
            exception=ConnectionError,
            n_failures=100,  # effectively infinite
        )
        failure_count = 0
        with fault_inject(bridge, "fetch_ohlcv", recipe):
            for _ in range(10):
                try:
                    bridge.fetch_ohlcv("EURUSD")
                except ConnectionError:
                    failure_count += 1
        # All 10 attempts failed without an unexpected exception
        assert failure_count == 10
