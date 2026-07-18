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

| Directory | Scope | Tests |
|-----------|-------|-------|
| `tests/engine/` | Engine lifecycle, weekend, PEK | 213 |
| `tests/inference/` | Inference pipeline, calibration | 71 |
| `tests/features/` | Feature building, labels, regime | 285 |
| `tests/domain/` | Domain entities, events, metrics | 192 |
| `tests/shared/` | Portfolio weights, sizing, kelly | 359 |
| `tests/backtests/` | Walk-forward, backtest pnl, adversarial | 208 |
| `tests/orchestrator/` | Orchestrator phases, admission | 293 |
| `tests/execution/` | Decision pipeline, entry gates, gates | 324 |
| `tests/position/` | Position manager, adaptive exit | 304 |
| `tests/ops/` | Monitor, MT5 client, serve, replay | 322 |
| `tests/services/` | Entry service, engine state, metrics | 169 |
| `tests/governance/` | Risk, health, halt conditions | 148 |
| `tests/monitoring/` | PSI drift, importance tracking, alerts | 156 |
| `tests/tools/` | Config docs, drift check, schema check | 162 |
| `tests/config/` | Registry, modes, domains | 141 |
| `tests/shadow/` | Shadow trades, WAL replay | 105 |
| `tests/labels/` | Triple-barrier, meta labels | 109 |
| `tests/state/` | State store, WAL persistence | 43 |
| `tests/pek/` | PEK contracts, admission engine | 31 |
| `tests/entry/` | Deferred entry, entry service | 34 |
| `tests/performance/` | Edge health, metrics | 18 |
| `tests/attribution/` | Attribution pipelines | 17 |
| `tests/chaos/` | Fault injection framework | 14 |
| `tests/temporal/` | Differential leakage detection | 18 |
| `tests/mutation/` | Mutation detection | 14 |
| `tests/signals/` | Signal contracts | 19 |
| `tests/alerting/` | PagerDuty, webhook channels | 18 |
| `tests/risk/` | Risk registry | 28 |
| `tests/logging/` | Logging configuration | 20 |
| `tests/benchmarks/` | Performance benchmarks | 21 |
| `tests/portfolio/` | HRP allocator | 17 |
| `tests/paper_trading/` | Top-level routing | 17 |
| `tests/integration/` | Cross-component integration | 21 |
| `paper_trading/dashboard/` | Vitest frontend tests | 236 |

## Key Test Patterns

### Determinism Tests

The WAL replay determinism tests verify that replaying the same event sequence
produces identical state. Run as part of CI:

```bash
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/orchestrator/test_wal_replay.py -v
```

### Circuit Breaker Tests

30 tests cover breaker scenarios in `tests/orchestrator/test_circuit_breaker_flatten.py`: cascade, concentration, single-asset drop,
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

**Last updated:** 2026-07-18
