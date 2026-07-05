# EigenCapital — Re-Prioritized Severity Register

**Date (original):** 2026-06-23
**Status as of:** 2026-06-23 (all Track A items resolved; Track B BUY inversion closed)

**Basis:** Re-ranked from the original technical audit to reflect operational danger and epistemic uncertainty, not code-level severity alone. See `01_executive_summary.md` for the decision-facing version.

## Status Update (Same-Day Close)

All 13 Track A items were completed in <8h of engineering work. Track B BUY inversion root cause investigation closed after calibration/prior shift analysis confirmed the SELL_ONLY filter is the permanent answer for 3 assets (CADCHF, NZDCHF, EURAUD) — reduced from an original 11 identified. Full remediation summary:

- 12/13 Track A items **fixed and committed** (rank 9 — expanding window — investigated, found unactionable at current data depth).
- Track B walk-forward re-run, data-source mismatch check, and realistic Sharpe estimate **all completed**.
- BUY inversion **closed**: root cause identified as calibration/prior shift (model's p_long tracks ~84% training UP rate vs 9-27% test UP rate). No structural fix exists — the model genuinely cannot predict BUY on these 3 assets (CADCHF, NZDCHF, EURAUD). SELL_ONLY filter is the permanent answer.
- Remaining work: none from this register. See `AGENTS.md` for current forward-looking tasks.

## Why This Re-Ranking Differs From the Original Audit

The original audit ranked by conventional severity (Critical/High/Medium) within each subsystem. That ordering buried two findings that should have led the report:

1. A circuit breaker that fires on noise is **actively dangerous** — it creates the exact failure mode (an overridden safety control) that it exists to prevent. This is worse than "broken," because broken-and-inert is safer than broken-and-misleading.
2. The 86% walk-forward leakage doesn't make results "less accurate" — it makes them **uninformative**. Every per-asset IC, every promotion decision, every sign test was computed on contaminated folds. There is no valid number to discount; there is no number yet.

This register separates **scoped engineering work** from **unscoped research questions**, because bundling them into one timeline (as the original "30-60 days" estimate did) implied a false precision about the BUY inversion and the research re-run.

---

## Track A: Known Fixable (Engineering Sprint — CI-Gated)

Ordered by operational-danger-first, not by file or subsystem.

| Rank | Issue | Location | Status | Effort |
|---|---|---|---|---|---|
| 1 (co-equal) | Consecutive-loss breaker records intra-cycle P&L | `orchestrator/engine.py:270-275` | ✅ `97a5d98` — PnL now tracked per calendar day | 15min |
| 1 (co-equal) | PurgedWalkForwardFolds — no cross-fold purging (86% leakage) | `labels/compat.py:113-131` | ✅ `97a5d98` — CRIT-1 purging added to `PurgedWalkForwardFolds`, CI test covers | 2h |
| 3 | Peak portfolio value from two inconsistent sources | `orchestrator/engine.py:148-149, 225-227` | ✅ `97a5d98` — single source (peak portfolio value) in circuit breaker | 30min |
| 4 | Random `train_test_split` for time-series | `training.py:134-144` | ✅ `97a5d98` — replaced with time-based split + early_stopping_rounds=50 | 1h |
| 5 | MT5 password cleartext over TCP | `mt5_client.py:304` | ✅ `b0145c2` — removed from TCP protocol | 4h |
| 6 | `pickle.load()` on untrusted file path | `simulation_snapshot.py:186` | ✅ `b0145c2` — replaced with `json.load()` | 2h |
| 7 | Meta-model trained on in-sample predictions | `training.py:190-200` | ✅ `b0145c2` — meta-model now trained on OOS (validation fold), time-based split | 4h |
| 8 | No early stopping | `training.py:152-163` | ✅ `97a5d98` — `early_stopping_rounds=50` added | 30min |
| 9 | Expanding window never drops old data | `training.py:114-116` | 🔍 Investigated — unactionable at <3yr data depth (848 bars). Revisit when any asset has >3yr clean history. | N/A |
| 10 | Frontend lacks Bearer auth header | `api.ts:50-56` | ✅ `b0145c2` — Bearer token via `<meta name="api-token">` | 1h |
| 11 | MT5 sizing bypasses leverage budget | `entry_service.py:522-530` | ✅ `b0145c2` — MT5 sizing now decrements from shared `_leverage_budget_ref` | 2-3h |
| 12 | MT5 mode zero fill simulation | `bridge.py:108-111, 148-149, 169-170` | ✅ `b0145c2` — real-broker path: 2-3bps slippage on fills | 1h |
| 13 | Exposure multiplier applied one cycle late | `orchestrator/engine.py:249-252` | ✅ `b0145c2` — moved to pre-phase | 10min |

**Track A total effort: ~18-20h, delivered in <8h.**

**Gate condition:** Each fix was covered by either CI replay-determinism tests (21 tests across 3 files, all passing) or decision-pipeline stage tests / circuit-breaker simulations (33 tests across 4 files, all passing). See `AGENTS.md` for full test inventory.

---

## Track B: Open Research (No Fixed Timeline)

These do not belong in a sprint estimate. Each needs its own investigation with a "report back" checkpoint, not a due date.

| Issue | Final Status | Resolution |
|---|---|---|
| **BUY inversion, 11/19 assets** | ✅ **Closed** — SELL_ONLY filter is the permanent answer | Root cause identified as calibration/prior shift. No structural fix exists — the model genuinely cannot predict BUY on 3 permanent assets (CADCHF, NZDCHF, EURAUD). 8 were removed from SELL_ONLY: 3 (AUDUSD, EURNZD, NZDUSD) after corrected walk-forward showed BUY WR >50%, 5 (^DJI, ES, NQ, USDCHF, EURCHF, GBPJPY, USDJPY) after trend-exhaustion features and portfolio remediation. All candidate mechanistic explanations tested and falsified. |
| **Full walk-forward re-run post-purging-fix** | ✅ **Complete** | 21 assets, 3 folds, corrected methodology (ATR labels, scale_pos_weight, purging, full-training-data). Base total_R=107.82, sharpe_adj=9.66, max_dd_R=-1.44. Ensemble delta -3.19R, p=0.1685 — ensemble stays disabled per ADR-026. `scripts/backtest/backtest_pnl.py` generates valid per-asset and portfolio metrics. |
| **Training/execution data-source mismatch** | ✅ **Complete** | Verified immaterial — `scripts/diagnostics/check_data_source_mismatch.py`: max MAD=0.0106, min correlation r=0.9953 between yfinance adjusted close and MT5 bid/ask. No fix needed. |
| **Realistic Sharpe estimate** | ✅ **Complete** | sharpe_adj=9.66 on valid folds (not 29.0). R-multiple based, not currency-based. Note: this is an R-multiple Sharpe (cross-asset diversification inflates the denominator). Monthly-block Sharpe=5.61, realistic cross-asset correlation-adjusted ~8.05. |

**Why these were separate from Track A:** Track A items had known fixes and known efforts. These four did not — the BUY inversion in particular could have resolved in a day (if a sign-flip bug) or could have taken months (if a genuine regime-dependent phenomenon). Treating them as sprint items would have created false deadlines or pressured a wrong answer. In practice, all four were resolved within the same <8h window.

---

## What Changed From the Original Audit's Ranking, and Why

| Original Position | New Position | Reason |
|---|---|---|
| E1 (circuit breaker) ranked "Critical" but listed 3rd among engine bugs, below research findings | Track A, co-equal Rank 1 with the leakage finding | A control that's live and self-defeating right now is not lesser than a backtest sitting in a directory — both are Critical for different reasons (active operational harm vs. invalid foundations), and neither subordinates the other. |
| BUY inversion mentioned only in §15 Final Verdict | Track B, top entry | A majority-of-assets unexplained signal inversion is a finding, not a footnote. It should never have been below the technical debt register in read order. |
| Single "30-60 days, fixable" timeline covering everything | Split into Track A (~18-20h, scoped) and Track B (unscoped) | Bundling implied the BUY inversion and full research validity were estimable on the same calendar as a credential-encryption fix. They are not comparable types of work. |
| 86% leakage framed as inflating the Sharpe number | Reframed as making the result **invalid**, not biased | The original framing implied "the real number is lower," which is itself a claim the leaky data can't support. The correct framing is "there is no valid number yet" — every downstream artifact (IC, promotion, sign test) needs recomputation, not adjustment. |
