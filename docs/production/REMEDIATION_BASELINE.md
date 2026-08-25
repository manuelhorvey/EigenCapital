# EigenCapital — Remediation Baseline

**Recorded:** 2026-08-25  
**Commit:** `0852d22` (chore: ignore dev-only scripts)  
**Python:** 3.14.7  
**OS:** Linux (Fedora-like, x86_64)

## Test Suite Baseline

```
1942 passed, 5 failed, 1 skipped in 7.68s
```

### Pre-existing Failures (5)

All in `tests/unit/production_qual/test_pre_trading.py`:

1. `TestBrokerConnection::test_correct_broker_state` — BrokerBoundaryConfig expects bare names (`AUDUSD`), test provides suffixed names (`AUDUSDm`). Symbol naming mismatch between production config and test fixtures.
2. `TestBrokerConnection::test_excessive_spread_blocks` — Spread check passes when test expects failure (spread data format mismatch).
3. `TestFullValidation::test_clean_start_all_pass` — Blocked by symbol mismatch (cascading from #1).
4. `TestFullValidation::test_authorization_to_dict` — Same cascading failure.
5. `TestFullValidation::test_authorization_to_markdown` — Same cascading failure.

**Root cause:** `BrokerBoundaryConfig.expected_symbols` uses bare names (`AUDUSD`) for the Exness production config, but test fixtures use suffixed names (`AUDUSDm`). This is a pre-existing test/data mismatch, not a remediation regression.

## Fingerprints (Pre-Remediation)

| Component | Fingerprint |
|-----------|-------------|
| R4 Manifest | `aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb` |
| RiskPolicy (default) | `a1eb1373fa11dff7c3dc0c22dbbedcac1857a04b45f252de9ec2d373aadbda6c` |
| CapitalBoundaryConfig | `95a1d9fea3f4ababe96eb50b5923475dc0a162a6fe80534ad7e4991d89ed3696` |
| BrokerBoundaryConfig | `a2164ee73ee59991fad37263ccd22a99909baba1bd0d9898e17e5902053ac199` |

## Lint Baseline

```
(to be recorded)
```

## Typecheck Baseline

```
(to be recorded)
```

## Dependencies

```
pytest==8.3.5, pytest-cov==6.1.1, ruff==0.15.13, mypy==2.3.0
numpy==2.3.5, pandas==2.3.3
```

No lockfile exists. `pyproject.toml` lists `dependencies = []` (empty).
