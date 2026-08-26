# Testing Architecture

This document describes the testing strategy and current status.

Last updated: 2026-08-26

## Current Status

| Suite | Count | Command | Status |
|---|---|---|---|
| Unit | 2,301 | `pytest tests/unit/` | ✅ All passing |
| P0 Safety | 44 | `pytest tests/unit/live/test_p0_safety.py` | ✅ All passing |
| Risk Enforcement | — | `pytest tests/unit/live/test_risk_enforcement.py` | ✅ All passing |
| Property | — | `pytest tests/property/` | ✅ Passing |
| Integration | — | `pytest tests/integration/` | Scaffolded |
| Simulation | — | `pytest tests/simulation/` | Scaffolded |
| Failure Injection | — | `pytest tests/failure_injection/` | Scaffolded |

## Test Categories

### Unit Tests (`tests/unit/`)

Tests individual models, layers, and subsystems in isolation.

| Directory | Scope |
|---|---|
| `tests/unit/test_*` | Core models, config, features |
| `tests/unit/live/` | Live trading modules |
| `tests/unit/production_qual/` | Qualification modules |

### P0 Safety Tests (`tests/unit/live/test_p0_safety.py`)

44 tests covering the complete safety architecture:

- Catastrophic protection
- Watchdog state machine
- Position attribution
- Fingerprint verification
- Durable audit
- Process supervision

### Risk Enforcement Tests (`tests/unit/live/test_risk_enforcement.py`)

Tests all seven risk gates:

- Broker connectivity
- Position count
- Account drawdown
- Daily loss
- Equity floor
- Position protection
- Fingerprint verification

### Architecture Audit (`tests/unit/test_architecture_audit.py`)

Continuously verifies layer-dependency rules:

- No upward imports
- Domain models are frozen dataclasses
- Invariants validated at construction

## Running Tests

```bash
# Full suite
make test

# Unit tests only
make test-unit

# Property-based tests
make test-property

# Specific test file
pytest tests/unit/live/test_p0_safety.py -v

# Specific test
pytest tests/unit/live/test_p0_safety.py::test_catastrophic_stop_calculation -v

# With coverage
pytest --cov=src/eigencapital tests/unit/

# Fail on first error
pytest -x tests/unit/
```

## Test Configuration

### pyproject.toml

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short"
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
]
```

### Coverage

Minimum gate: 80% (configured in pyproject.toml)

```bash
# Check coverage
pytest --cov=src/eigencapital --cov-report=term tests/unit/
```

## Test Design Principles

### Fail-Closed

Tests verify that safety controls block unauthorized behavior, not that they allow authorized behavior.

### Invariant Testing

Domain models validate invariants at construction:

```python
# This should raise InvariantViolation
with pytest.raises(InvariantViolation):
    Instrument(instrument_id="", name="Invalid")
```

### Property-Based

Property tests verify invariants hold for arbitrary valid inputs:

```python
@given(st.integers(min_value=0, max_value=1000))
def test_position_count_never_exceeds_limit(n):
    # ...
```

### Failure Injection

Tests verify correct behavior during failures:

- Broker disconnect
- Stale data
- Corrupted state
- Process crash
- Duplicate instances

## What Tests Verify

| Claim | Test | Evidence |
|---|---|---|
| Max positions = 19 | `test_risk_enforcement.py` | Unit test |
| Max position = $5,000 | `test_config_consistency.py` | Unit test |
| Fingerprint enforced | `test_p0_safety.py` | Unit test |
| Catastrophic SL | `test_p0_safety.py` | Unit test |
| Watchdog state machine | `test_p0_safety.py` | Unit test |
| Foreign quarantine | `test_p0_safety.py` | Unit test |
| Layer dependencies | `test_architecture_audit.py` | Architecture test |

## What Tests Do NOT Verify

- Live execution quality (requires real broker)
- Slippage/spread (requires live data)
- Holding period economics (requires time)
- Correlation stability (requires history)
- Strategy profitability (requires evidence)

## Pre-existing Failures

Currently: **0 pre-existing failures**

All 2,301 tests pass.

## Adding New Tests

### For New Safety Controls

1. Add test to `tests/unit/live/test_p0_safety.py`
2. Verify both pass and fail cases
3. Test edge cases (boundary values, missing data)
4. Test crash recovery behavior

### For New Risk Gates

1. Add test to `tests/unit/live/test_risk_enforcement.py`
2. Test pass condition
3. Test block condition
4. Test missing data behavior
5. Test short-circuit behavior

### For New Models

1. Add test to `tests/unit/test_<model>.py`
2. Test construction with valid data
3. Test construction with invalid data (invariant violation)
4. Test serialization round-trip
5. Test equality and hashing

## CI Integration

Tests run automatically on:

- Every commit (planned)
- Pull request
- Nightly (full suite)

```yaml
# .github/workflows/test.yml (planned)
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -e ".[research]"
      - run: pytest tests/unit/ -v
```
