# Testing — EigenCapital

## Test Framework

Python tests use `pytest` with optional coverage reporting. Dashboard tests use `vitest`.

```bash
# Full Python test suite
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/ -v --tb=short -x

# With coverage
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/ \
  --cov=. --cov-report=term-missing --cov-fail-under=70 -v --tb=short -x

# Single test file
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/engine/test_engine_weekend.py -v

# Dashboard tests
cd paper_trading/dashboard && npx vitest run --reporter verbose

# Chaos tests
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/chaos/ -v --tb=short
```

## Test Structure

| Directory | Scope | Count |
|-----------|-------|-------|
| `tests/engine/` | Engine lifecycle, weekend, PEK | ~200 |
| `tests/inference/` | Inference pipeline, ensemble, calibration | ~80 |
| `tests/features/` | Feature building, labels, regime | ~60 |
| `tests/domain/` | Domain entities, events, metrics | ~120 |
| `tests/shared/` | Portfolio weights, sizing, kelly | ~50 |
| `tests/backtests/` | Walk-forward, backtest pnl, adversarial | ~200 |
| `tests/orchestrator/` | Orchestrator phases, admission | ~150 |
| `tests/position/` | Position manager, adaptive exit | ~100 |
| `tests/governance/` | Risk, health, halt conditions | ~80 |
| `tests/chaos/` | Fault injection framework | 13 |
| `tests/temporal/` | Differential leakage detection | ~30 |
| `tests/mutation/` | Mutation detection | ~20 |
| `paper_trading/dashboard/` | Vitest frontend tests | 135 |

## Key Test Patterns

### Determinism Tests

The WAL replay determinism tests verify that replaying the same event sequence
produces identical state. Run as part of CI:

```bash
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/test_replay_determinism.py -v
```

### Circuit Breaker Tests

33 tests cover breaker scenarios: cascade, concentration, single-asset drop,
synthetic AUD crash, sequential losses.

### Config Schema Validation

```bash
python tools/check_config_schema.py
```

Run in CI after every config change.

## Chaos Testing Framework

The `tests/chaos/` directory provides a deterministic fault injection framework for testing system resilience under adverse conditions.

**Core concepts:**
- `FaultRecipe` — configuration object describing a fault: target function, failure mode (exception, return override, latency), and activation constraints (count limit, probability)
- `fault_inject` — context manager that patches a function for the duration of a `with` block. Automatically replaces the original on exit, even under exceptions
- `ChaosRegistry` — manages a collection of active fault recipes with scoping and cleanup

**Example:**
```python
from tests.chaos.chaos_tools import FaultRecipe, fault_inject

recipe = FaultRecipe(
    target="module.function",
    exception=ConnectionError("MT5 bridge timeout"),
    count=3,  # Fail only on first 3 calls
)
with fault_inject(target, recipe):
    result = system.process_cycle()  # First 3 calls fail, 4th+ succeeds
```

**Supported fault types:**
| Type | Parameters | Use Case |
|------|-----------|----------|
| Exception | `exception`, `count` | Simulate transient errors (network, API, broker) |
| Return override | `return_value`, `probability` | Force specific return values at random |
| Latency | `latency_ms`, `probability` | Simulate slow responses or timeouts |

**Run:**
```bash
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/chaos/ -v --tb=short
```

## Coverage Targets

| Area | Target | Current |
|------|--------|---------|
| Core engine | 80% | ~75% |
| Governance | 80% | ~82% |
| Features | 70% | ~65% |
| Dashboard | 70% | ~68% |

Coverage is measured with `pytest-cov` and reported to Codecov.

---

**Last updated:** 2026-07-05
