# Executive Summary

## Bottom line

EigenCapital is a **well-tested, carefully guarded single-strategy system** whose *containment* controls are stronger than its *accounting and evidence* controls.

The codebase has 3,644 tests, clean `ruff`/`mypy`, a hash-chained audit log, a single-instance guard, fail-closed risk recovery, and an explicitly frozen R4 signal with a fidelity guard test. Those are real strengths.

However, the three capabilities that make capital scaling defensible are **not wired into the live path**:

1. independent equity/capital reconciliation (P0-1),
2. a capital-event ledger (P0-2),
3. a durable decision→intent→order→fill audit chain (P0-3).

The components exist in the tree (`EventLedger`, `DurableAudit`, `ReconciliationEngine`) but the live loop does not use two of them, and the reconciliation it does call compares broker positions against a "internal state" constructed **from the same broker snapshot** — so it cannot detect divergence.

Separately, two statistics used to justify research findings are **demonstrably wrong** (Holm/BH correction, PBO), and research provenance does not reproduce. That invalidates the reported research confidence, independent of live-trading safety.

## What is sound

- **R4 signal discipline.** Signal math is frozen; `signal_vol_scale_reference=0.50` is the consumed divisor and `vol_target_annual=0.10` is decorative, per approved `EC-AUDIT-001` Alternative A. Guarded by `tests/unit/test_r4_signal_fidelity.py`.
- **Containment.** Single-instance claim with exit 75; `--force-regime` forbidden in loop mode; catastrophic-SL safety supervisor on by default with a kill-switch flag file; corrupted risk audit fails closed; `mitigation_mode=halt` fails closed.
- **Test hygiene.** Unit, property, integration, failure-injection and dashboard suites all collected and run; property suite passed 3 consecutive times (no reproduction of the P1-3 flake); lint/type gates clean.
- **Dashboard security posture.** Constant-time API key comparison, Bearer/X-API-Key support, per-IP rate limit, restricted CORS, security headers, loopback bind, credential never in URLs (legacy `?token=` tolerated only in a transition window), DTO masking on the shared stream.

## What blocks a capital increase

| # | Blocker | Evidence |
|---|---|---|
| 1 | No independent equity truth | Loop never compares broker equity to an internal ledger; `runtime_state.json` shows `daily_start=5107.83` against `daily_loss.baseline_equity=18177.0` |
| 2 | No capital-event ledger | `EventLedger` has zero callers outside its own package |
| 3 | No durable execution chain in live path | `DurableAudit`/`AuditLog` are imported only by `live/campaign.py` |
| 4 | Reconciliation cannot detect divergence | `InternalState` built from the same `positions_get()` result |
| 5 | Execution audit trail not persisted | Reconciliation state file is never written (counter bug) and the dashboard reads a differently-named file anyway |
| 6 | Research evidence not reproducible | Provenance hash mismatch; PBO always 1.0; Holm/BH anti-conservative; R1–R6 artifacts absent |

## Risk framing

- **Not** a finding that the strategy is unsafe to run at its current size. Containment controls are adequate for a small, single-account deployment.
- **Is** a finding that the system cannot yet *prove* what happened to capital, or *independently* verify that broker and internal state agree. Those are prerequisites for scaling, not trading-day necessities.

## Verdict

**MAJOR ARCHITECTURAL OR SAFETY WORK REQUIRED** before any capital increase.

Capital increase is **NOT authorized**. Continued operation at current size is acceptable **only** under the existing containment controls (safety supervisor running with `configs/r4_safety.enabled` present, current risk limits unchanged, no stop-loss gate relaxation). Detailed answers are in `09_CAPITAL_READINESS_VERDICT.md`; sequencing is in `10_REMEDIATION_ROADMAP.md`.

## Highest-value fixes, in order

1. Wire `EventLedger` and `DurableAudit` into the live cycle and key them by a single `cycle_id`/`decision_id`.
2. Replace tautological reconciliation with a **persisted internal position ledger** derived from confirmed fills, and persist the result at the path the dashboard reads.
3. Fix stop-loss validation (`None`/negative/non-numeric must not count as protected) and make invalid SL a hard block.
4. Correct Holm/BH and PBO; re-run affected research verdicts.
5. Add capital-event/equity history with an append-only hash chain and a daily reconciliation checkpoint.
6. Resolve the `max_absolute_weight_error` contradiction: implement the advertised veto or delete the claim.
