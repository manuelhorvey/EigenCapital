# Production Evidence Index

This document indexes all evidence artifacts for the EigenCapital $5K controlled qualification.
Each artifact is designated as authoritative (governance-critical) or informational.

Last updated: 2026-08-26

## Current Qualification Status

**🟢 LIVE — CONTROLLED $5K QUALIFICATION**

| Gate | Status | Evidence |
|---|---|---|
| Frozen R4 identity | ✅ Verified | Fingerprint verified at startup |
| Build/config fingerprint | ✅ Fail-closed | 5-component verification |
| Foreign positions | ✅ 0 | Position attribution audit |
| R4 ownership | ✅ 100% | Attestation report |
| Position protection | ✅ 19/19 | Catastrophic SL on all positions |
| Catastrophic layer | ✅ Proven | Adversarial audit 10/10 |
| Position-count enforcement | ✅ Proven | 19 ≤ 19 configured max |
| Equity/daily-loss controls | ✅ Proven | Risk enforcement gates |
| Watchdog | ✅ Proven | State machine tests |
| Disconnect/recovery | ✅ Proven | Auto-reconnect in loop |
| Fresh T=0 | ✅ Frozen | T0_R4-5K-20260826-v2 |
| Live attestation | ✅ Valid | Attestation report |
| Adversarial tests | ✅ 10/10 | Adversarial audit report |
| Supervisor verification | ✅ 3/3 | Dry-run reports |

## Evidence Artifacts

### T=0 Snapshots (Authoritative)

| File | Date | Campaign | Status |
|---|---|---|---|
| `T0_R4-5K-20260826_6d4a41335841.json` | 2026-08-26 | R4-5K-20260826 | Historical (pre-$5K) |
| `T0_R4-5K-20260826-v2_d803eca9f10e.json` | 2026-08-26 | R4-5K-20260826-v2 | **Current** |

### Qualification Reports (Authoritative)

| File | Date | Purpose | Status |
|---|---|---|---|
| `supervisor_dryrun_20260826_225800.json` | 2026-08-26 | 9-gate verification | PASS |
| `supervisor_dryrun_20260826_230056.json` | 2026-08-26 | Re-verification | PASS |
| `supervisor_dryrun_20260826_230059.json` | 2026-08-26 | Re-verification | PASS |
| `supervisor_dryrun_20260826_230101.json` | 2026-08-26 | Re-verification | PASS |
| `adversarial_audit_20260826_225814.json` | 2026-08-26 | 10-fault injection | 10/10 PASS |
| `adversarial_audit_20260826_225834.json` | 2026-08-26 | Re-run after fix | 10/10 PASS |
| `attestation_20260826_225850.json` | 2026-08-26 | Ownership proof | VALID |

### Runtime Evidence (Informational)

| Directory | Purpose | Retention |
|---|---|---|
| `evidence/position_evidence.jsonl` | Hourly position snapshots | Rolling 30 days |
| `reports/r4_loop/decisions.jsonl` | Order execution audit | Rolling 30 days |
| `reports/r4_loop/loop.log` | Loop operational log | Rolling 7 days |

### Safety Architecture (Authoritative)

| Module | Purpose | Tests |
|---|---|---|
| `catastrophic_protection.py` | Disaster stop-loss boundary | 44 P0 tests |
| `watchdog.py` | Blind-window detection | State machine tests |
| `position_attribution.py` | R4/foreign classification | Quarantine tests |
| `fingerprint_verifier.py` | Build integrity verification | Fail-closed tests |
| `durable_audit.py` | Crash-resistant audit trail | Persistence tests |
| `supervisor.py` | Process supervision | PID management tests |

### Risk Documentation (Authoritative)

| Document | Purpose | Status |
|---|---|---|
| `CAPITAL_SCALING.md` | Capital semantics & scaling (consolidated) | Current |
| `R4_TRADE_ECONOMICS_AUDIT.md` | Entry/exit economics | Current |
| `R4_ENTRY_QUALITY_AUDIT.md` | Entry signal analysis | Current |
| `R4_EXIT_RISK_AUDIT.md` | Exit mechanism analysis | Current |
| `R4_CAPITAL_SCALING_RISK_AUDIT.md` | Scaling risk analysis | Current |
| `R4_RISK_IMPROVEMENT_PLAN.md` | Risk improvement plan | Current |
| `R4_P0_SAFETY_REMEDIATION_PLAN.md` | P0 remediation plan | Complete |
| `R4_P0_SAFETY_REMEDIATION_REPORT.md` | P0 remediation report | Complete |

### Audit Reports (Informational)

| Report | Purpose | Date |
|---|---|---|
| `reports/r4_economics_audit/` | Trade economics analysis | 2026-08-26 |
| `reports/r4_safety/` | Safety audit evidence | 2026-08-26 |

## Code-to-Evidence Traceability

| Claim | Source Code | Test | Evidence | Status |
|---|---|---|---|---|
| Max positions = 19 | `config.py` | `test_risk_enforcement.py` | Live verification | VERIFIED |
| Max position = $5,000 | `config.py` | `test_config_consistency.py` | Config audit | VERIFIED |
| Fingerprint enforced | `fingerprint_verifier.py` | P0 safety tests | Startup log | VERIFIED |
| Catastrophic SL | `catastrophic_protection.py` | P0 safety tests | Broker verification | VERIFIED |
| Watchdog state machine | `watchdog.py` | P0 safety tests | Adversarial audit | VERIFIED |
| Foreign quarantine | `position_attribution.py` | P0 safety tests | Adversarial audit | VERIFIED |
| Auto-reconnect | `r4_rebalance_loop.py` | Integration | Loop log | VERIFIED |
| XAUUSD admitted | `config.toml` | Config check | Live position | VERIFIED |
| US30 admitted | `config.toml` | Config check | Live position | VERIFIED |
| 97.4% signal coverage | Signal computation | Coverage analysis | Evidence snapshot | VERIFIED |

## Unresolved Evidence Gaps

1. **Entry slippage** — No baseline established; need live fill data
2. **Holding period economics** — Research evidence exists; live confirmation pending
3. **MAE/MFE patterns** — Evidence collection started; need 30+ days
4. **Correlation stability** — Rolling analysis started; need longer history
5. **Gap risk** — XAUUSD/BTC gap scenarios need live stress testing
6. **Windows support** — No conformance test evidence
7. **Strategy capacity** — Formal capacity limit not documented
