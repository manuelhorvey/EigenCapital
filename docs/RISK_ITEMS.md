# Risk Items — ARCHIVED

> **Archived 2026-07-05.** Superseded by `AGENTS.md` and
> `docs/PRODUCTION_SYSTEM_SPEC_v1.md`. Risks are tracked via ongoing
> production monitoring. Content preserved below for historical reference.

---

## 1. Circuit Breaker Calibration (Group 1)

**Status**: Open. First calibration completed 2026-06-22 via `scripts/simulations/circuit_breaker_sim.py`.

**Risk**: The breaker has never fired empirically (max 4 consecutive portfolio losses observed; threshold=7). The Monte Carlo calibration uses a 14-month bull-market sample (Oct 2024–May 2026) that contains no true crisis. A threshold that appears well-calibrated against bootstrap-from-bull-market data may fire too early, too late, or at the wrong severity during a genuine regime break.

**Mitigation**:
- `circuit_breaker_sim.py` produces a threshold sensitivity table and a dual-conditional recommendation ("assuming next 12 months resemble last 14" + explicit caveat)
- Re-run after 6 months of live data, or immediately after a -10R drawdown live, whichever comes first
- The breaker's consecutive-loss condition (currently threshold=7) is the only well-calibrated check — drawdown-pct and vol-spike thresholds remain manually set defaults

**Next action**: None until revisit trigger fires.

---

## 2. BUY Inversion (Group 2)

**Status**: Closed as "known unknown, monitored." Root cause unknown. Two causal hypotheses (carry for CHF+OTHER, DXY for equities) falsified by walk-forward counterfactual ablation 2026-06-20. SELL_ONLY filter is the empirically validated treatment.

**Risk**: 3 assets have an inverted BUY signal (CADCHF, NZDCHF, EURAUD — p_long > 0.5 predicts the wrong direction). The filter suppresses BUY, so the system never acts on these signals — but if the underlying inversion were to change (asymmetry healing or the SELL side also degrading), the filter would need updating.

**Monitoring**:
- `scripts/diagnostics/check_direction_win_rates.py` provides two signals:
  1. **Fast signal**: live SELL WR on SELL_ONLY assets compared to OOS baseline. If SELL WR drops >10pp below baseline (~77% → ~67%), the model is degrading regardless of asymmetry.
  2. **Slow signal**: OOS BUY WR trend on SELL_ONLY assets. If >30%, reopen investigation — asymmetry may be healing.
- Run this script monthly or after every retrain.

**Trigger to reopen investigation**: OOS BUY WR on any of the 3 SELL_ONLY assets exceeds 30%, or live SELL WR on any SELL_ONLY asset drops >10pp below baseline.

---

## 3. Retraining Decay (Group 3, Item 4)

**Status**: UNANSWERABLE with current methodology. This is a structural limitation of the walk-forward pipeline design, not a data-volume problem.

### The Problem

Two independent confounds make retraining decay unmeasurable in the current pipeline:

1. **Model age ↔ training data volume (confounded)**: The expanding-window design means each successive fold's model was trained on strictly more data than the previous fold. A performance drop in later folds could be:
   - Genuine decay (the model forgot its old patterns)
   - A harder test window (the later test period was intrinsically harder to predict)
   - Or a model-quality improvement masked by an even harder test window

   These are inseparable. A rolling-window design (fixed train size, sliding forward) would cleanly separate model age from data volume.

2. **Lookahead contamination**: The live model cannot be tested against earlier historical windows because it was trained on data those windows hadn't observed at the time. Testing against them would be lookahead-contaminated.

### Proposed Fix: Rolling-Window Walk-Forward Variant

**Scope estimate**: ~150 lines of new code, ~60 minutes.

The fix requires modifying one function in the walk-forward pipeline: instead of `train_idx = idx[:test_start - gap]` (expanding), use `train_idx = idx[max(0, test_start - gap - train_size): test_start - gap]` (rolling window with fixed `train_size` like 756 bars = 3 years).

Files affected:
- **`paper_trading/inference/training.py`**: `PurgedWalkForwardFolds` or the fold-construction call site needs a `window=mode` parameter (`"expanding"` | `"rolling"`). When `window="rolling"`, compute `train_start` as `max(0, fold_end - gap - train_window_bars)` instead of `0`.
- **`scripts/backtest/walk_forward_backtest.py`**: Propagate the `--window` and `--train-window-bars` flags through to the training config.
- **`configs/paper_trading.yaml`**: Add optional `walkforward_window` and `walkforward_train_bars` keys.

Comparable scope to `scripts/diagnostics/check_chf_correlation.py` (~120 lines, 1 data source) or `scripts/training/retrain_counterfactual.py` (~180 lines, ablation logic + 5-fold WF).

**Recommendation**: Build this now rather than waiting 12 months for a clean decay signal. The system's remaining unknowns (breaker calibration against unseen crises, BUY inversion mechanism) all share the same property: you don't know you're wrong until something expensive happens. A rolling-window variant is cheap to build, has zero interaction with the statistical or execution layer, and converts "unanswerable" from a dead end into a backlog item with a known shape. If built now, you can start collecting the clean decay measurement immediately rather than deferring it to a hypothetical future retrain cycle.

**If not built now**: Re-measure after the next annual retrain, comparing the new model's performance on pre-retrain vs post-retrain OOS windows. But note this still won't fully separate age from data volume until the rolling-window variant exists.

---

## 4. MT5 Bridge Failure (Group 3, Item 5)

**Status**: Closed as "alerting gap, not an execution gap." Added WARNING-level log when MT5 fetch fails and yfinance fallback is used (2026-06-22).

**Risk**: MT5 positions become unmanaged for trailing/breakeven/flips during a bridge outage. Broker-side SL/TP survive, so max loss per position is bounded. Paper trading continues independently via PaperBroker.

**Mitigation**:
- WARNING log in `safe_download()` when MT5 fetch fails — operator can detect bridge health from daily log check
- At $107 demo equity, zero real capital at risk

**Escalation condition**: When real capital is deployed (equity > $10K on MT5 side), add a dashboard indicator for bridge health and automated position-surveillance.

---

## 5. Synthetic Adversarial Stress Testing

**Status**: Not yet implemented.

**Risk**: Crisis replay covers only Oct 2024–May 2026 — does not include 2008 GFC, 2015 SNB shock, or COVID crash. The circuit breaker simulation can only sample from this period.

**Proposed addition**: Extend `scripts/backtest/crisis_replay.py` to inject synthetic −3R days across all assets (simulating a correlated crash) and verify that the circuit breaker fires and flatten executes. This would test the breaker's behavior outside any observed regime.

**Scope estimate**: ~80 lines, comparable to `scripts/diagnostics/check_chf_correlation.py`.

---

## 6. Equity Cluster Concentration

**Status**: Closed as "alarm removed 2026-07-01." ^DJI remains in the portfolio as the sole US_EQUITY asset (ES, NQ removed). The equity cluster alarm was recommendation-only and guarded against ES/NQ/^DJI same-side concentration; with only one US equity survivor, the alarm is unnecessary.

**Historical risk**: When ES and NQ were both SELL_ONLY (2026-06-20 through 2026-06-30), they shared concentrated directional exposure with ^DJI. The HealthMonitor equity cluster alarm flagged same-side positions across the three equity-Index assets but did not force-flatten. ^DJI was removed from SELL_ONLY 2026-06-26 after trend-exhaustion features improved its BuyWR above breakeven. ES and NQ were removed from the portfolio on 2026-07-01; ^DJI was retained as the sole US_EQUITY asset.

**Mitigation (historical)**: Equity cluster alarm in HealthMonitor was a recommendation-only signal — no force-flatten path. Alarm code is now a comment in `paper_trading/orchestrator/health.py:105` marking removal.

**Active risk substitute**: None. With no equity indices in the portfolio, the concentration cluster has zero holdings. The position concentration check (Phase 3e, `net_short_concentration_threshold`) covers portfolio-wide same-side skew if a future caught regime arises.

---

## 7. Post-Fix/Pre-Fix Data Pooling

**Status**: Documented in AGENTS.md and LIVE_CONTRACT.md.

**Risk**: Any trades executed prior to commit f15af30 (2026-06-19) used a regime-dead ensemble. These should not be pooled with post-fix trades in any exit-reason or performance aggregate.

**Mitigation**: Historical walk-forward parquets are post-fix era only (Oct 2024–May 2026 OOS data). Live trading started after all fixes. No pooling issue exists unless someone investigates pre-fix state.db snapshots.
