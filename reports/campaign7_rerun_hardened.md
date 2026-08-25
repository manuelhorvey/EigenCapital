# CAMPAIGN 7 RERUN — HARDENED GOVERNANCE

**Snapshot:** immutable C7 tick snapshot (unchanged)
**Generated:** 2026-08-25 01:45 UTC
**Engine:** corrected per-bar cost accounting (one-way 6.5/11 bps)
**Family:** 72 evaluations (18 hyp × 4 horizons); Bonferroni within-family
**Cumulative ledger:** 205 program evaluations

---

## VERDICT DISTRIBUTION (hardened)

| Verdict | Count | IDs |
|---|---|---|
| **REJECTED** | 18 | TF-001, TF-002, TF-003, AI-001, AI-002, AI-003, SD-001, SD-002, SD-003, PI-001, PI-002, PE-001, PE-002, LL-001, LL-002, LL-003, CO-001, CO-002 |

## TOP RESULTS UNDER HARDENED ACCOUNTING

| ID | HP | Gross | Net | Adv | DD | WF | p_raw | p_fam | p_cum | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| CO-002 | 30m | -0.76 | -21.22 | -29.28 | -100.0% | 0% | 1.000 | 1.000 | 1.000 | rejected |
| SD-001 | 30m | -0.11 | -22.65 | -30.25 | -100.0% | 0% | 1.000 | 1.000 | 1.000 | rejected |
| PE-001 | 30m | -0.37 | -24.94 | -35.91 | -100.0% | 0% | 1.000 | 1.000 | 1.000 | rejected |
| AI-002 | 30m | -0.03 | -31.84 | -41.28 | -100.0% | 0% | 1.000 | 1.000 | 1.000 | rejected |
| PE-002 | 30m | -0.67 | -34.31 | -47.45 | -100.0% | 0% | 1.000 | 1.000 | 1.000 | rejected |
| AI-003 | 30m | +0.48 | -35.83 | -46.73 | -100.0% | 0% | 1.000 | 1.000 | 1.000 | rejected |

## TF-003 DISPOSITION UNDER HARDENED GOVERNANCE

- Corrected net Sharpe (base): **-60.88** (adverse -81.19)
- Max DD (net): -100.0%
- WF consistency: 0%
- p_raw 1.000 → p_family 1.000 → p_cumulative 1.000
- Final verdict: **REJECTED** (reasons: negative_net, catastrophic_dd, excessive_degradation, wf_inconsistent, oos_negative, instrument_dependent, permutation_insignificant)

## DECISION

**ZERO survivors under hardened governance.
The broker-microstructure branch is FROZEN**, consistent with the M1–1H OHLCV freeze. The measurement-system defects that motivated this rerun remain fixed for all future campaigns.
