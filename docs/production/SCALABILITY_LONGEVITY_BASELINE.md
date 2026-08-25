# EigenCapital — Scalability & Longevity Baseline

**Recorded:** 2026-08-25  
**Commit:** `f32845a`  
**Branch:** `fix/production-readiness-p0` (pre-merge)

## Environment

| Item | Value |
|------|-------|
| Python | 3.14.7 |
| OS | Linux (x86_64) |
| pytest | 8.3.5 |
| numpy | 2.3.5 |
| pandas | 2.3.3 |
| ruff | 0.15.13 |
| mypy | 2.3.0 |
| mt5linux | (RPyC bridge) |

## Fingerprints (Machine-Verifiable)

```
R4_FINGERPRINT=aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb
RISK_FINGERPRINT=a1eb1373fa11dff7c3dc0c22dbbedcac1857a04b45f252de9ec2d373aadbda6c
CONFIG_FINGERPRINT=3601517d862735e8
LIVE_RISK_FINGERPRINT=9683391fee12be0e
```

## Identity

| Item | Value |
|------|-------|
| Account | 436921728 |
| Environment | demo |
| Broker | exness |
| Server | Exness-MT5Trial9 |
| Strategy | risk_conditioned_continuation R4.0 |
| T=0 Equity | 5010.94 |
| Max Concurrent | 8 |
| Max Position | 1500 |
| Max Daily Loss | 250 |
| Campaign Duration | 30 days |

## Test Suite

```
2018 passed, 5 failed, 1 skipped
```

### Pre-Existing Failures (5)

All in `tests/unit/production_qual/test_pre_trading.py`:
- Symbol naming mismatch: BrokerBoundaryConfig expects bare names (`AUDUSD`), test fixtures use suffixed names (`AUDUSDm`).
- Root cause: Exness production uses bare names; paper/development configs use suffixed names.

## Known Gaps (P0)

| Gap | Risk | Status |
|-----|------|--------|
| DisconnectRecovery not wired to live loop | Positions unprotected during disconnect | NOT STARTED |
| No process crash recovery | Dead system requires manual restart | PARTIAL (PID file exists) |
| No order idempotency | Possible duplicate orders | NOT STARTED |
| Risk state not persisted | Peak equity/daily loss lost on restart | PARTIAL (daily tracker persisted) |
| No failure injection tests | Untested failure paths | NOT STARTED |

## Verification Command

```bash
python3 -c "
from eigencapital.fidelity.r4_manifest import R4ConfigManifest
print(R4ConfigManifest().compute_identity())
"
# Expected: aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb
```
