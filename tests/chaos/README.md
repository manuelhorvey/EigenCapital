# Chaos Testing Framework

## Purpose

Deterministic, scoped fault injection for production-resilience testing.
The chaos layer is **test-only** — excluded from production imports via
pre-commit hook.

## Core Concepts

### FaultRecipe

Configuration for a single fault scenario:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | str | required | Scenario name |
| `description` | str | required | Human-readable description |
| `exception` | type | None | Exception to raise on failure |
| `message` | str | "fault-injection" | Exception message |
| `n_failures` | int | 1 | Number of consecutive failures before recovery |
| `fail_probability` | float | 1.0 | Probability each call fails |
| `return_value` | Any | None | Value to return when not failing |
| `delay_seconds` | float | 0.0 | Simulated latency |

### `fault_inject` context manager

Monkey-patches a callable for the duration of the context:

```python
from tests.chaos.chaos_tools import fault_inject, ConnectionDropOnce

def test_orchestrator_survives_connection_drop():
    with fault_inject(mt5_client, "fetch_ohlcv", ConnectionDropOnce()):
        with pytest.raises(MT5ConnectionError):
            mt5_client.fetch_ohlcv("EURUSD", years=2)
```

The patch restores the original on context exit (even on exceptions) and
stacks correctly under nesting.

### ChaosRegistry

Catalog of registered chaos scenarios for introspection in test reports.

## Pre-built Recipes

| Recipe | Behavior |
|--------|----------|
| `ConnectionDropOnce` | Fail once then recover — simulates transient disconnect |
| `ConnectionDropN(n)` | Fail N times then recover |
| `LatencyInjector(seconds)` | Add delay without failing |

## Files

| File | Role |
|------|------|
| `chaos_tools.py` | FaultRecipe, fault_inject, ChaosRegistry, pre-built recipes |
| `test_chaos_tools.py` | 13 tests covering the chaos framework |

## Writing a New Chaos Test

1. Define a `FaultRecipe` (or use `ConnectionDropOnce`)
2. Wrap the target callable with `fault_inject`
3. Assert the system degrades gracefully (logs warning, retries, etc.)
4. Assert the original function is restored after the context exits
