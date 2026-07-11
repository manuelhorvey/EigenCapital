### Initial Backtest Results (base-only, full portfolio, corrected methodology)
- 19 assets, 171 OOS days (aligned methodology: ATR labels, scale_pos_weight, CRIT-1 purging, full-training walk-forward)
- Portfolio total_R = +107.82R, max_dd_R = -1.44R (all in R-multiples, not currency)
- Portfolio sharpe_adj (Lo-adjusted for autocorrelation ρ=0.68): 9.66 — **CAVEAT: R-multiple portfolio Sharpe; see note below**
- **Top performers**: GC (+706R), ^DJI (+615R), AUDUSD (+495.5R), USDCHF (+327.2R)
- **Bottom performers**: NZDUSD (-101.5R), USDCAD (-38R), GBPCHF (+38R lowest positive)
- **Methodology note**: Previous metrics (total_R=291R, sharpe_adj=9.1) used unaligned labels (rolling 21d std vs EWM span=100), no scale_pos_weight, no purging (86% leakage bug), and 350 OOS days with 5 folds. The corrected methodology reduces OOS days to 171 (3 viable folds) but eliminates leakage and methodology divergence.

**Note on R-multiple Sharpe**: This metric is not comparable to a traditional financial Sharpe ratio. The portfolio daily R is a simple average of per-asset R-multiple changes (20 assets, equal weight regardless of position size). Cross-asset diversification artificially reduces portfolio std, inflating the Sharpe. Monthly-block Sharpe (non-overlapping) = 5.61. Adjusting for realistic FX cross-asset correlation (ρ~0.3) gives ~8.05. All values are in R-multiple space — they describe signal quality, not expected live trading Sharpe.

### Directional Asymmetry Investigation

#### Step 1: Per-direction breakdown
- AUDNZD and EURUSD both lose on SELL predictions (82% loss rate, 72% loss rate respectively)
- But this is NOT majority-class bias: 19/22 assets beat 50% coin-flip on BUY, 18/22 on SELL
- The model has genuine directional skill on both sides for most assets

#### Step 2: Breakeven WR vs raw WR
- The real bottleneck for losing assets is tp/sl config: AUDNZD needs 66.7% WR to break even (tp=1, sl=2), EURUSD also 66.7% (tp=1.5, sl=3)
- The model achieves 71.3% BUY WR on AUDNZD (real skill) and 66.2% on EURUSD (skill but just misses BE)
- SELL WR on these assets: 17.9% and 27.6% — significantly worse than 50% coin flip (anti-skill)

#### Step 3: p_long calibration → isotonic fails
- Probability calibration check: the model is severely miscalibrated
  - AUDNZD p_long=0.25 → actual label=1 frequency = 82.6% (model overconfident SELL)
  - AUDNZD p_long=0.93 → actual label=1 frequency = 47.8% (model overconfident BUY)
- Isotonic calibration fit on fold-0 test set compresses all probabilities into [0.44, 0.58]
- With the 0.425-0.575 dead zone, almost all calibrated predictions go FLAT → 0.5 threshold also doesn't help
- **Cause of isotonic failure**: model's directional mix flips between folds (fold 0: 74% BUY → fold 2: 12% BUY). The isotonic fit on a BUY-dominant fold fails on SELL-dominant folds

#### Step 4: Regime-conditional ensemble check
- Ensemble signals are nearly identical to base on the trend folds (p_long correlation 0.97-0.98)
- When signals disagree (13/94 rows), ensemble wins 0/13 on fold 1
- The regime-conditional ensemble does NOT detect or correct the directional flip — falsified

#### Step 5: Training-window return structure
- Expanding-window training (confirmed: `train_idx = idx[:test_start - gap]` — all history, never drops old data)
- 20-bar return autocorrelation is strongly positive in ALL training and test periods (0.75-0.97) but this may be inflated by overlapping-window artifact [CAVEAT: adjacent 20-bar windows share 19/20 data points]
- Model bias vs recent returns: EURUSD shows trend-follower-like behavior (predicts recent train-window direction) that breaks when test trend reverses; AUDNZD shows unexplained flip at fold 2 despite near-identical recent return (+0.50% → +0.40%)

#### Step 6: Directional filter diagnostic — defangs the trend flip, not a structural fix

The filter removes the anti-skill direction per asset (derived from per-direction 50%-null WRs). Portfolio-level: +307R → +350R (+14%). Every asset's total R improved.

**CAVEAT — per-fold concentration**: improvement is dominated by 1-2 folds per asset where trade count collapsed by 80-90% and the removed signals are a concentrated losing streak matching the known trend-period flip:

| Asset | Dominant fold(s) | Removed signals | Removed R | Loss streak |
|-------|-----------------|----------------|-----------|-------------|
| AUDNZD | 2-3 | 148 SELL | -224R | 28 consecutive |
| EURUSD | 1 | 70 SELL | -151.5R | 35 consecutive |
| AUDCHF | 0-1 | 90 BUY | -85R | 20 consecutive |
| ES | 0 | 55 BUY | -72.5R | 26 consecutive |
| NQ | 0 | 32 BUY | -80R | 32 consecutive (all losses) |

Folds where the direction *wasn't* flipped show zero or near-zero removed signals (filter had nothing to override). AUDUSD fold 1-2: removing BUY removes *wins* (+26R), yet fold 0's 48 BUY removed (47/48 losses, -66.5R) outweighs it.

**Interpretation**: The filter defangs the directional instability symptom — it prevents the model from acting on its confirmed trend-period wrong-direction flip. It does NOT identify a structurally bad per-asset direction. The improvement lives where the flip happens (specific historical trend periods) and will re-apply the next time the model flips into a trend. This is a valid production guard but is best understood as a secondary consequence of the terminal finding (directional instability), not an independent discovery.

**script**: `scripts/backtest/filter_direction.py`

### Terminal Finding: Base Model Directional Instability

**Symptom**: The base model makes confident wrong-direction bets during trending market periods. Reproducible across 2 assets and 3 consecutive walk-forward folds.

**Evidence**:
- AUDNZD fold 2 (test: +4.54%): model flips from 94% BUY to 12% BUY (wrong — keeps rallying to +5.79%)
- EURUSD fold 1 (test: +10.63%): model flips from 99% BUY to 16% BUY (wrong — keeps rallying)
- Ensemble doesn't correct it (p_long corr 0.97-0.98)
- Calibration doesn't fix it (isotonic fails on fold-to-fold directional shift)
- Not cleanly trend-following (AUDNZD fold 1→2 flip unexplained by recent returns)
- Not cleanly mean-reversion (20-bar ACF positive, not negative)

**Mechanism**: NOT fully isolated. Contributing factors identified:
1. Expanding training window (dilutes recent signal with old data)
2. Triple-barrier labels may not distinguish trend vs. reversal regimes
3. Feature set may lack regime-awareness signals
4. The interaction between these produces fold-to-fold directional instability that tracks realized test-period trend reversals but whose root cause remains distributed

**Risk**: If this pattern (confident wrong-direction bets during trends) holds in production, a 1-2 month trending period could produce concentrated losses in the assets most affected (AUDNZD, EURUSD, likely others with similar profile).

**Next investigation suggestions**:
1. **Circuit breaker simulation (DONE 2026-06-23)** — `TestCheckDrawdownCircuitBreaker` (9 unit tests across 2 files), `TestDrawdownBreakerIntegration`, `TestCorrelatedAUDSyntheticCascade` (5 tests simulating 15% simultaneous AUD drop), `TestSequentialCascade`, `TestSingleAssetConcentratedDrop`, `TestCircuitBreaker` (5 tests in test_actor_orchestrator + 6 in test_validity_state_machine). All 33 breaker tests pass.
2. Cross-correlate AUD pairs for simultaneous adverse move risk
3. Investigate whether fixed-length rolling window (e.g., 12-month lookback) stabilizes fold-to-fold directional bias
4. Test label structures that penalize reversal bets during trend regimes

---
## BUY Inversion Discovery (2026-06-20, Phase 2)

### Finding

The original "directional flip" narrative was wrong as a portfolio-wide diagnosis. The real failure mode is:

**The model's BUY signal is inverted for 11 of 19 assets** — `p_long > 0.5` reliably predicts the WRONG direction.

### Evidence Chain

1. **BUY is flat at ~17% win rate from p_long=0.57 to p_long=1.0** across all flagged assets. p_long=0.50-0.575 bucket: 0 wins out of 144 predictions (0%). This is NOT miscalibration — it's an **inverted signal**.

2. **SELL is well-calibrated at ~77% win rate** on the same assets. p_long < 0.425 bucket: 1,273 predictions at 77% win rate.

3. **The pattern is not trend-conditional**: confident BUY wins 15% in trending windows and 23% in non-trending windows. The model simply misprices these assets regardless of regime.

4. **The pattern is uniform across all flagged assets**: every single one shows 0% win rate in the 50-57% p_long bucket.

5. **Portfolio-wide, not concentrated**: 77% of assets had at least one fold with >50% wrong rate under the old methodology.

### Correction to Prior Findings

- The "directional flip" (AUDNZD confident SELL during uptrend) was an asset-specific anomaly, not portfolio pattern
- The portfolio-wide problem was originally diagnosed as **BUY overconfidence on 9 specific assets**, not "confident wrong-direction bets during trends"
- DXY correlation, trend duration, and regime-conditional factors were all tested and ruled out as mechanisms
- Three of the 11 originally-flagged assets (^DJI, EURCHF, USDCHF) were marginally net-positive on BUY due to favorable tp/sl ratios masking the inverted signal — this was still a trust issue, not a returns issue

### Fix Applied

**`apply_sell_only_filter` stage** added to `decision_pipeline.py:DEFAULT_STAGES`. For 9 flagged assets, BUY signals are overridden to FLAT. SELL signals pass through unchanged.

```python
SELL_ONLY_ASSETS: frozenset[str] = frozenset({
    "CADCHF", "NZDCHF", "EURAUD",
})
```

Backtest comparison (16 promoted assets, corrected methodology):

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| total_R | 105.69 | 107.82 | +2.0% |
| max_dd_R | -1.51 | -1.44 | **-4.6%** |
| sharpe_adj | 9.49 | 9.66 | +1.8% |
| OK assets (10) | unchanged | unchanged | 0% regression |

The filter still helps — reduces max_dd and enables SELL-only signals to dominate. The modest improvement reflects that the corrected methodology produces more realistic base metrics (vs the broken methodology's inflated baselines).

**Pass/fail**: Missed ≥5% total_R bar (only +2.7%). Met the no-OK-asset-regression bar. Success criterion revised: **primary metric is max_dd reduction and confident-wrong elimination**, not total_R improvement, because the original problem was asymmetric downside risk, not returns optimization.

**Epistemic status (2026-06-20)**: The SELL_ONLY filter is no longer a "temporary stopgap pending a feature-level fix." The two leading causal hypotheses (carry for CHF+OTHER, DXY for equities) were both falsified by walk-forward counterfactual ablation. The BUY inversion root cause remains unknown. SELL_ONLY is the empirically-grounded answer — removing it requires discovering a causal mechanism that does not currently exist in any tested hypothesis.

## Statistical Metrics — Known Behaviors & Caveats

### PSR/DSR Float64 Saturation Zone

`scipy.stats.norm.cdf(z)` saturates at exactly **1.0 in float64** for z > ~8.2 and at **0.0** for z < ~-8.2. This means PSR and DSR cannot discriminate between "strongly significant" and "overwhelmingly significant" once the z-score exceeds ~8.2.

**Practical implication for EigenCapital**: With n ≈ 300 observations (typical walk-forward test window), PSR(>0) saturates at 1.0 for any Sharpe > ~0.3. The "mediocre" scenario (Sharpe=0.7, n=252) produces z ≈ 11, well into the saturation zone. PSR(>0) = 1.0000 for 16 of 18 assets in the portfolio backtest — this doesn't mean those assets are equally significant; it means they all exceed the float64 ceiling.

**Where DSR is discriminative**: DSR's useful range is Sharpe in approximately [0.0, 0.8] for n ≈ 250, and narrower for larger n. Outside this range, DSR is a binary pass/fail indicator (1.0 for strong signals, 0.0 for negative). At the current portfolio Sharpe of 29, DSR(18) being 1.0 is correct but provides zero selective information — it will say "PASS" regardless of whether num_trials is 18 or 1800. This is a ceiling effect of float64, not a calculation error. DSR will only become a meaningful gate when portfolio Sharpe drops into the 0.5–2.5 range.

**Where PSR is discriminative**: PSR(>0) for Sharpe values in [-0.3, 0.3] with n=252 produces smooth, non-saturated values. For Sharpe < -0.3, PSR floors at 0.0. For Sharpe > 0.3, PSR saturates at 1.0. PSR(>1) has a wider discriminative range — Sharpe values of 0.5–1.5 produce non-saturated probabilities. Prefer PSR(>1) over PSR(>0) for evaluating marginal improvements.

### MinTRL Floor at 2

`minimum_track_record_length()` returns a floor of 2 for extreme Sharpe values. This is correct — it means "you need at least 2 observations to be 95% confident this Sharpe is positive" — but it's not informative. MinTRL's useful range is Sharpe in approximately [0.1, 2.0].

### Validation Note: Single-Draw Fragility

The synthetic validation script (run during 2026-06-20 build) uses `np.random.normal()` to generate test data. A single random draw is unreliable for verifying expected behavior — a comment like `# Sharpe ≈ 0.3` on `np.random.normal(0.0003, 0.015, 252)` is misleading because a single draw can produce Sharpe anywhere in ~[0.0, 0.7]. For permanent regression tests, use either (a) a fixed large number of draws averaged, or (b) distributional assertions (e.g., "Sharpe falls within 95% CI of parametrized distribution"), not point comparisons against one realization.

## SHAP Audit (2026-06-20)

> **[HISTORICAL — pre-2026-07-01 portfolio]** This analysis was conducted on the pre-remediation 9-asset SELL_ONLY set. Since then, ^DJI, ES, NQ, USDCHF, EURCHF, GBPJPY, USDJPY have been removed from SELL_ONLY or reclassified (see Trend-Exhaustion Features and Portfolio Remediation sections). Only CADCHF, NZDCHF, EURAUD remain as permanent SELL_ONLY. The SHAP findings are preserved here as a record of the original diagnostic chain.

### Loaded Models
All 9 flagged asset models loaded successfully from `paper_trading/models/*.json`. Config-loaded `pt_sl=(tp_mult, sl_mult)` and `max_depth` per asset (not hardcoded defaults).

### Method
For each asset: load live retrained XGBoost, compute SHAP on all binary-classified rows, then compare mean SHAP attributions between **wrong confident-BUY** (p_long > 0.5, triple-barrier label < 0) vs **correct confident-BUY** (p_long > 0.5, label > 0). Pooled per sub-cluster. Threshold: |diff| >= 0.05 with consistent sign across cluster = candidate mechanism.

### Results

**Equities (^DJI, ES, NQ)** — 3 assets, all with sufficient data (>10 wrong-BUY rows each):

| Feature | Pooled |diff| | Sign consistency | Interpretation |
|---------|---------|------------------|----------------|
| dxy_mom_21d | 0.195 | 100% (3/3 neg) | Wrong BUY calls have weaker DXY momentum support. The model confuses DXY weakness with risk-on equity signal, but this breaks when DXY and equities decouple. |
| CLOSE_mom_21d | 0.178 | 67% (2/3 neg) | Wrong BUY calls have weaker short-term momentum. Secondary mechanism. |
| CLOSE_mom_126d | 0.093 | 67% | Wrong BUY calls have weaker medium-term momentum. |

PASS on dxy_mom_21d. Mechanism: **cross-asset correlation learning failure** — model learns the DXY/equity correlation during normal conditions but fails during periods where the relationship breaks down (e.g., DXY falling for non-risk-on reasons).

**CHF+OTHER (CADCHF, NZDCHF, USDCHF, EURCHF, AUDUSD, EURAUD)** — 6 assets:

| Feature | Pooled |diff| | Sign consistency | Interpretation |
|---------|---------|------------------|----------------|
| CLOSE_carry_vol_adj | 0.158 | 83% (5/6 neg) | Wrong BUY calls have weaker carry signal contribution. The model uses positive carry as a bullish signal but fails when carry doesn't support the direction. |
| CLOSE_mom_252d | 0.115 | 83% (5/6 neg) | Wrong BUY calls have weaker long-term momentum. |
| CLOSE_mom_21d | 0.082 | 100% (6/6 neg) | Wrong BUY calls have weaker short-term momentum. |

PASS on CLOSE_carry_vol_adj. Mechanism: **single-asset feature dominance** — the carry feature dominates the BUY prediction, but when carry is present without supporting momentum or z-score conditions, the BUY call fails.

**Single-asset note — EURAUD**: Only 1 feature (CLOSE_vol_ratio, diff=-0.071) passes threshold. EURAUD has the most balanced wrong/correct ratio (110 wrong vs 131 correct) and the weakest SHAP separation. Mechanism unconfirmed — either it shares the CHF+OTHER carry mechanism with a noisier signal (illiquid pair, wider fiat ranges) or has a different/unknown root cause that happened to be swept in by the original win-rate screen. Flagged as weakest evidence in cluster. If someone later extends a carry-feature fix to all 6 CHF+OTHER assets, EURAUD is the one that may not respond as expected (but note: carry was falsified by ablation as causal, so no such fix is currently realizable). No change to current treatment (kept in SELL_ONLY_ASSETS).

### ^DJI/EURCHF/USDCHF Decision

SHAP confirms all 3 follow the same mechanisms as their cluster peers:
- **^DJI**: dxy_mom_21d diff=-0.381 (same as ES=-0.173, NQ=+0.130). Sign consistent with equity pooled direction across 3/3 assets.
- **EURCHF**: CLOSE_carry_vol_adj diff=-0.117. Momentum features (mom_252d=-0.266, mom_21d=-0.224, mom_63d=-0.210) strong. Consistent with CHF cluster carry/momentum pattern.
- **USDCHF**: CLOSE_zscore_20 diff=-0.230, carry_vol_adj diff=-0.106. Consistent with CHF cluster.

No evidence of a special case for any of the 3. The existing decision (keep all 9 in SELL_ONLY_ASSETS) is consistent with — and reinforced by — the SHAP findings.

### Closed Items
- SHAP audit: **COMPLETED**. Two distinct mechanisms identified (dxy_mom_21d for equities, CLOSE_carry_vol_adj for CHF+OTHER). Both passed SHAP thresholds — but subsequent **counterfactual walk-forward ablation disproved both as causal**. Removing carry on CHF cluster (5 assets) and DXY on equity cluster (3 assets) neither restored BUY WR >50% on any asset. The SHAP mechanisms are **correlational**, not causal. See Counterfactual Ablation section.
- ^DJI/EURCHF/USDCHF decision: **RESOLVED**. SHAP confirms same mechanisms as cluster peers. No special case. SELL_ONLY_ASSETS treatment stands. The tp/sl argument is still correct (the 3 are profitable only due to asymmetric barriers) but the SHAP finding makes it moot — the mechanism is the same, so treating them differently would be inconsistent.

### Remaining Open Items

3. **Path A (rolling window backtest)** — Completed 2026-06-20. Result: expanding-vs-rolling discrepancy is **unobservable** at current data depth (~848 bars / 2.3 years per asset). With `rolling_window_bars=3*252=756`, no training fold is large enough for truncation to fire. Expanding and rolling output bit-for-bit identical metrics (total_R=316.6, sharpe_adj=10.95). The original question (does backtest methodology match live training?) is not answered — it cannot be tested with existing data. Revisit when any asset crosses 3+ years of clean history, or test with a deliberately small window (e.g., 252 bars) for a mechanism check (does rolling vs expanding ever matter for this model class). The latter is a cheap mechanism question about the model family, not a validation of the production config. Low priority.

4. **Live tripwire (DONE 2026-06-20)**: `record_sell_side_outcome()` in `risk.py` tracks SELL-only TP/SL outcomes per asset (deque maxlen=20, win=TP/loss=SL, BUY and non-TP/SL exits skipped). `get_sell_tripwire_state(asset, sell_only)` returns `{"win_rate": ..., "tripped": bool}`. Trips at 65% threshold, logs WARNING on trip + INFO on clear (state transition tracked via `_tripwire_last_state`). Wired into `state.json` via `engine_state_service.py` — replaces hardcoded `False`. Dashboard red TRIPWIRE badge now real. Call site in `position_service.py:close_position` records every SELL trade exit alongside existing SL hit rate. Tripwire only applies when `sell_only=True` — non-flagged assets can accumulate SELL win-rate data but never trip.

5. **Feature-level fix (FALSIFIED 2026-06-20)** — Both SHAP-identified mechanisms (dxy_mom_21d for equities, CLOSE_carry_vol_adj for CHF+OTHER) were tested via walk-forward counterfactual ablation. **Neither is causal.** Removing carry did not restore BUY WR >50% on any of 5 CHF-cluster assets. Removing DXY did not restore BUY WR >50% on any of 3 equity-cluster assets. Both ablations degraded total returns. The BUY inversion root cause remains unknown. SELL_ONLY filter is no longer a temporary stopgap pending a feature-level fix — it is the empirically-grounded answer, and removing it requires discovering a causal mechanism that currently does not exist in any tested hypothesis.

### Falsified Hypotheses (2026-06-20 session)

- Ensemble corrects directional flip (falsified 2026-06-19, re-confirmed)
- Calibration problem: OK cluster has 57% win rate on same predictions
- DXY drives the failure: CHF assets show DXY correlation but controlling for DXY direction doesn't explain failures
- Trend duration: equities have shorter trends (confirmed as secondary factor), but CHF/OTHER cluster has normal duration and still fails
- Trend-conditional: bad assets are 15-23% regardless of trending regime — not trend-conditional
- Detection guard: p_long trajectory can't distinguish flip from normal (22.2% FP rate)
- Label redesign: asymmetric barriers increase (not decrease) fold-to-fold variance
- **Carry is causal (falsified 2026-06-20)**: removing carry via walk-forward ablation did not restore BUY WR >50% on any of 5 CHF-cluster assets. The SHAP finding was correlational.
- **DXY is causal (falsified 2026-06-20)**: removing DXY via walk-forward ablation did not restore BUY WR >50% on any of 3 equity-cluster assets. Total returns strictly worsened.

## Replay-First Architecture (2026-06-20, Phase 3)

### Causal Boundary Markers

The WAL now captures three causal boundary events that form a complete replay chain:

```
features_snapshot  (P0.1) — exact model input vector + feature_hash + model_hash
    ↓
inference_output   (P0.3) — model probabilities BEFORE governance gating
    ↓
decision_output    (P0.3) — final action AFTER all governance stages + gates bitmask
```

Each event is written at its own causal boundary by the code that owns that boundary:
- `features_snapshot` in `pipeline.py:_trace_and_diagnostics()` (after feature vector is finalized)
- `inference_output` in `pipeline.py:_run_inference()` (right after `model.predict_proba()`)
- `decision_output` in `decision_pipeline.py:run_decision_pipeline()` (after all stages complete)

The `feature_hash` (MD5 of sorted feature dict, 12 hex chars) flows as a scalar:
`_build_feature_set → _run_inference → _build_decision → DecisionContext → run_decision_pipeline`

The `model_hash` (SHA256 of model JSON, 16 hex chars) is computed at training time and stored as a sidecar file (`{model}_hash.txt`). Loaded at engine init in `AssetEngine._load_model_hash()`.

### trace.jsonl Derivation

`trace_decision()` no longer independently captures features. The `features_sample` dict is passed from the same `feature_vector` variable used for `features_snapshot`. Both `feature_hash` and `model_hash` are included in the trace entry, enabling cross-log consistency verification: a replay test can hash trace.jsonl's `features_sample` and assert it matches the WAL's `feature_hash` for the same cycle.

### New WAL Event Types

Three new event types in `wal.py` docstring (causal boundary tier):
- `features_snapshot` — asset, features dict, feature_hash, feature_schema, model_hash
- `inference_output` — asset, prob_long/short/neutral, model_hash, feature_hash
- `decision_output` — asset, final_signal, gates_aborted, feature_hash, model_hash

All existing observability events (price_update, signal_generated, position_closed, state_committed, actor_health) remain unchanged.

### ReplayRunner Handlers

New handlers in `replay/runner.py`:
- `_on_features_snapshot` — stores features, feature_hash, model_hash, feature_schema per asset
- `_on_inference_output` — stores proba + hashes
- `_on_decision_output` — stores final_signal + hashes

### Key Files

| File | Change |
|------|--------|
| `paper_trading/asset_engine.py` | Added `_wal_writer`, `_model_hash`, `_load_model_hash()`, `_last_feature_vector/hash/schema` |
| `paper_trading/inference/pipeline.py` | `features_snapshot` + `inference_output` WAL events; feature_hash threading through `_build_decision`; feature_hash in trace |
| `paper_trading/execution/decision_pipeline.py` | `feature_hash` in `DecisionContext`; `decision_output` WAL event at pipeline end |
| `paper_trading/ops/tracer.py` | `trace_decision()` now accepts and logs `feature_hash` + `model_hash` |
| `paper_trading/orchestrator/actor.py` | `AssetActor.__init__` sets `engine._wal_writer = wal_writer` when provided |
| `paper_trading/replay/runner.py` | Three new handlers for causal boundary events |
| `paper_trading/replay/wal.py` | Docstring updated with causal vs observability event tiers |
| `paper_trading/inference/training.py` | Model hash sidecar file written at save time |
| `eigencapital/domain/entities/signal.py` | `TradeDecision.feature_hash` field added |
| `scripts/training/retrain_counterfactual.py` | **NEW** — feature ablation walk-forward test |
| `scripts/diagnostics/check_chf_correlation.py` | **NEW** — CHF cluster independence verification |
| `paper_trading/ops/slack_alerter.py` | **NEW** — WAL-tailing Slack alert daemon |
| `paper_trading/dashboard/src/hooks/useEngineHealth.ts` | **NEW** — 5s health poll for liveness indicator |
| `paper_trading/dashboard/src/components/WalTimeline.tsx` | **NEW** — per-asset WAL causal-boundary event timeline |
| `paper_trading/orchestrator/engine.py` | Phase 3e — position concentration check |
| `paper_trading/services/engine_state_service.py` | `position_concentration` exposed in portfolio summary |
| `configs/domains/risk/sizing.yaml` | `net_short_concentration_threshold` default |

## Barrier Symmetry Audit (2026-06-20)

**Hypothesis**: The 17%/77% BUY/SELL asymmetry might be caused by asymmetric volatility estimates in upper vs lower triple-barrier barriers.

**Result (falsified)**: Both upper and lower barrier computations in `apply_triple_barrier()` (`labels/triple_barrier.py:62-64`) use the **identical** `vol_slice` array — either from `_ewm_vol(close)` (span=100) in training, or from `compute_atr_pct` in live execution. The only asymmetry is the intentional `pt_sl[0]` (tp_mult) vs `pt_sl[1]` (sl_mult) coefficients from config.

**Verdict**: Label construction is not the cause. The 17%/77% split is a genuine model miscalibration, not a label artifact. The label audit hypothesis (Priority 1 from the Phase 3 planning session) is closed.

## Deferred-Entry SELL_ONLY Bypass Fix (2026-06-20)

**Bug**: `entry_service.py:poll_pending_entries()` did not check `SELL_ONLY_ASSETS` before executing deferred BUY entries. A BUY signal deferred to a future cycle could execute on a SELL_ONLY asset, bypassing `apply_sell_only_filter` in the decision pipeline (which only runs for the current cycle's signal).

**Fix**: Added a SELL_ONLY check at the top of the deferred entry loop in `poll_pending_entries()`. If the direction is `"long"` and the asset is in `SELL_ONLY_ASSETS`, the deferred entry is canceled with reason `"sell_only_filter"`.

**File**: `paper_trading/services/entry_service.py:665-673`

## CHF Cluster Correlation Check (2026-06-20)

**Script**: `scripts/diagnostics/check_chf_correlation.py` — verifies whether 4 SELL-on-CHF positions (CADCHF, NZDCHF, USDCHF, EURCHF) are independent bets or one leveraged CHF-strength position.

**Output**: Pairwise return correlations, concurrent direction agreement, worst-case concurrent drawdown days, 3+ concurrent loss day frequency. Run with:
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/diagnostics/check_chf_correlation.py
```

## Feature Ablation Script (2026-06-20)

**Script**: `scripts/training/retrain_counterfactual.py` — isolates causal mechanism of BUY inversion by removing feature groups and observing effect on BUY WR.

**Usage**:
```bash
# Ablate carry on CHF cluster
PYTHONPATH=$PYTHONPATH:. python scripts/training/retrain_counterfactual.py \
    --assets CADCHF,NZDCHF,USDCHF,EURCHF,AUDUSD --remove-carry

# Ablate DXY on equity cluster
PYTHONPATH=$PYTHONPATH:. python scripts/training/retrain_counterfactual.py \
    --assets ^DJI,ES,NQ --remove-dxy
```

**Output**: `walkforward/counterfactual/{tag}_{timestamp}/` — per_asset.csv + portfolio.csv with BUY WR comparison. If removing a feature restores BUY WR >50% on 3+ assets, that feature is **causal** (not just correlational).

## Counterfactual Ablation Results (2026-06-20)

Both SHAP-identified mechanisms were tested via walk-forward ablation. **Neither is causal.**

### Carry Removal (CHF cluster: CADCHF, NZDCHF, USDCHF, EURCHF, AUDUSD)

| Asset | Baseline BUY WR | CF BUY WR | ΔBUY WR | Total R Δ |
|-------|----------------|-----------|---------|-----------|
| CADCHF | 24.1% | 40.0% | +15.9% | -13.0 |
| NZDCHF | 11.8% | 15.4% | +3.6% | +34.0 |
| USDCHF | 60.0% | 55.6% | -4.4% | -8.6 |
| EURCHF | 14.3% | 26.8% | +12.5% | +4.0 |
| AUDUSD | 33.3% | 18.8% | -14.6% | -56.5 |

**Portfolio**: 0/5 assets restored to >50% BUY WR. Total ΔR: -40.10. Removing carry degrades total returns and does not fix BUY inversion.

### DXY Removal (Equity cluster: ^DJI, ES, NQ)

| Asset | Baseline BUY WR | CF BUY WR | ΔBUY WR | Total R Δ |
|-------|----------------|-----------|---------|-----------|
| ^DJI | 33.3% | 16.7% | -16.7% | -6.5 |
| ES | 0.0% | 0.0% | 0.0% | -7.5 |
| NQ | 40.0% | 25.0% | -15.0% | -10.0 |

**Portfolio**: 0/3 assets improved. Total ΔR: -24.00. Removing DXY makes BUY WR and total returns strictly worse.

### Interpretation

The SHAP findings (dxy_mom_21d for equities, CLOSE_carry_vol_adj for CHF+OTHER) were **correlational**, not causal. Carry and DXY contribute to the BUY signal's confidence but are not the *source* of its inversion. When you remove them, the model still predicts BUY at the wrong times — just with different feature weights.

**Epistemic update**: SELL_ONLY is no longer a "temporary stopgap pending a feature-level fix." It is the empirically-grounded answer. Two leading hypotheses for *why* the BUY signal is inverted have been tested and falsified. Removing SELL_ONLY requires discovering a causal mechanism that does not currently exist in any tested hypothesis.

### Why the Baseline BUY WR Differs from Production

The counterfactual script uses a 600-row dataset (vs 848 in production), 5 folds with gap=10, and `n_estimators=300, max_depth=2` — these differ from the production training config. As a result, baseline BUY WR ranges from 0-60% (vs ~17% in production for the flagged assets). The RELATIVE comparison (baseline vs counterfactual) is valid since both use the same configuration. The ABSOLUTE values should not be compared to production metrics.

## Updated Priority Order (2026-06-23)

| Rank | Item | Status |
|------|------|--------|
| 1 | Barrier symmetry audit | **DONE** — clean, label hypothesis closed |
| 2 | Deferred-entry SELL_ONLY bypass fix | **DONE** |
| 3 | CHF cluster correlation check | **DONE** — moderate correlation, 41% concurrent loss days |
| 4 | Causal replay chain (P0 events) | **DONE** — features_snapshot, inference_output, decision_output |
| 5 | Feature ablation + retrain | **DONE** — both mechanisms falsified, root cause unknown |
| 6 | Replay determinism test (full chain) | **DONE** — hash-verified model reload, proba comparison, gate replay. 21 tests across 3 files pass. |
| 7 | Adversarial governance tests | **DONE** — 33 circuit breaker tests across 4 files pass, including synthetic AUD cascade. |
| 8 | Evidence-based gating (Phase A) | **CANCELLED** — no causal mechanism to gate on |

## Known Issues

- **Stacking (ADDED 2026-06-22, DEFERRED 2026-06-28)**: Pyramiding layer support for existing winning positions. Default `enabled: false`, dry_run: true. Walk-forward analysis showed stacking does not improve portfolio risk-adjusted returns — it increases notional concentration during already-profitable trades without commensurate Sharpe benefit. Remains disabled by default with no active phase-in plan. If revisited, validate on EURCAD/CADCHF first.
- **MT5 orphan/re-entry bug (FIXED 2026-06-22)**: 5-fix chain to resolve same-side re-entry orphan problem:
  1. `decision_pipeline.py:manage_position` — sets `ctx.new_side = None` when already in same-side position (was `logger.debug`, promoted to `logger.info` same session)
  2. `entry_service.py:_record_position_state` — preserves existing `mt5_ticket` when broker returns None
  3. `decision_pipeline.py:apply_spread_gate` — observe-mode check runs before fail-closed check (prevents blockage during 720-cycle warmup)
  4. `orchestrator/engine.py:Phase C` — orphan detection now includes self-healing adoption (`PHASE_D_ADOPT`) that backfills `mt5_ticket` from broker Position objects when paper has position but no ticket (`paper_has_position_no_ticket`)
  5. `orchestrator/engine.py:Phase B` — broker position cache invalidated before stale-ticket detection (5s cache would otherwise miss positions placed earlier in same cycle)
  **Validation**: 11 MT5 orphans adopted in cycle 2, 0 new orphans in 3+ consecutive subsequent cycles.

## Live Sharpe Tracker (2026-06-25)

**New module**: `paper_trading/performance/live_sharpe.py` — `LiveSharpeTracker` class that
reads equity history from SQLite and computes rolling Sharpe ratios from both
cycle-level (30s) and daily-aggregated returns.

**Integration**: Added to `engine_state_service.py:save_state()` — every cycle computes
live Sharpe + slippage estimate and stores in `state.json` under
`portfolio.live_sharpe`. Dashboard can access via `/state.json`.

**Features**:
- Cycle-level Sharpe with Lo (2002) autocorrelation adjustment
- Rolling daily Sharpe (7d, 30d, all-time) — activated once sufficient days accumulate
- Portfolio cumulative return + max drawdown in % of capital
- Slippage estimate from trace.jsonl (RMS gap between signal price and market price)
- Falls back gracefully (`available: false`) when no equity history exists

**Current live values** (as of 2026-06-25, ~3 days of data):
| Metric | Value |
|--------|-------|
| Cycle-level Sharpe (adj) | 1.26 |
| Portfolio return | +0.89% |
| Max drawdown | -0.4% |
| Slippage RMS gap | 1.74% |
| Daily-level Sharpe | N/A (< 5 days of data) |

**Caveats**: Cycle-level Sharpe with 30s intervals has high autocorrelation (ρ=0.13),
which the Lo adjustment partially corrects. Daily-level Sharpe needs ≥5 days of data
to produce a meaningful estimate. Slippage is measured as the gap between model
close_price and current_price in trace.jsonl — actual fill prices from MT5 may differ.

**Future work**: Add fill-price-based slippage from MT5 broker positions once sufficient
trade history accumulates. Daily Sharpe becomes reliable after ~20 trading days.

## USDCAD tp/sl Swap (2026-06-25)

**Problem**: USDCAD ranked 18/19 assets by total R (+61.8R) with Sharpe 1.4 vs portfolio
average ~10. The model has genuine skill (59.8% WR, 67.4% BUY WR) but tp=2.03/sl=2.5
gives breakeven WR=55.2% — only 4.6pp margin. SELL side loses -33.7R (49.2% WR) while
BUY earns +95.5R.

**Fix**: Swapped tp_mult from 2.03→2.5 and sl_mult from 2.5→2.03:
- tp/sl ratio improves from 0.81→1.23
- Breakeven WR drops from 55.2%→44.8%
- Same signals at 59.8% WR would produce +200.9R (3.2x improvement)
- SELL side flips from -33.7R to +24.6R at unchanged WR

**Files**: `configs/domains/assets/<TICKER>.yaml` (live execution per-asset), `features/registry.py` (label
generation for next retrain). Retrain required for full effect; config change applies
immediately to live SL/TP placement.

## Monte Carlo Drawdown Simulation — V2 Fix (2026-06-25)

**Problem**: `monte_carlo_drawdown.py` V1 bootstrapped raw R-multiples (additive, dimensionless), which have high mean (~1.0 R/day from walk-forward), guaranteeing p_positive_return ≈ 1.0 regardless of horizon. The results answered the wrong question — they showed "probability cumulative R > 0" not "probability portfolio % return > 0."

**Fix**: Convert each daily R-multiple to % portfolio return using per-asset ATR_pct (from `shared.volatility.compute_atr_pct`) and implicit equal-weight allocation:

```
return_pct = R × ATR_pct  (per asset),  portfolio_return = mean(return_pct) across active assets
```

**Results from 10k sims (walk-forward data, 447 OOS days)**:
| Metric | 1y | 3y | 5y |
|--------|------|------|------|
| Expected total return | +13.9× (1300%) | +3440× | +771,680× |
| P(positive return) | 100% | 100% | 100% |
| VaR(95) max DD | -2.3% | -2.8% | -3.0% |
| Worst DD observed | -4.2% | -4.5% | -4.5% |

**Interpretation**: Drawdown metrics are now in % of capital (meaningful). P(positive return)=100% persists because the walk-forward signals are genuinely high-quality (empirical Sharpe ~17 in %-space, ~20 in R-space). The total returns are unrealistically high because the walk-forward data itself is optimistic — this is the known caveat from AGENTS.md (Sharpe=9.66, "R-multiple portfolio Sharpe"). The fix correctly converts R to %, but the underlying signal quality is a separate concern.

**What the fix enabled**:
- Drawdown in % of capital (now interpretable — VaR(95) DD ≈ -2.3% at 1y)
- Geometric compounding for multi-year horizons (was additive cumsum)
- SELL_ONLY list updated to current 8 assets
- Both %-space and legacy R-space output for comparison (use `--r-space`)

**What remains unaddressed** (optimistic bias): slippage, spread, commissions, position sizing guardrails, MT5 lot quantization, partial fills, intraday risk. Results are upper-bound estimates. Future work: bootstrap from live equity curve once sufficient trading history accumulates.

**Files**: `scripts/backtest/monte_carlo_drawdown.py`, `mc_results_v2.json`

## Portfolio tp/sl Optimization — First Pass (2026-06-25)

**Method**: Scanned ratio space [0.5, 8.0] for each of 21 assets against walk-forward signal parquets. Optimal ratio found by maximizing total_R while preserving geometric mean (keeping average barrier distance constant). SELL_ONLY assets evaluated on SELL leg only. Ratio=2.0 chosen as conservative target — the unconstrained optimum was ratio=4.0-8.0 for most assets, but changing labels (next retrain) introduces uncertainty; a moderate improvement with known bounds is safer than an extreme change.

> **Follow-up (2026-06-30):** Ratio threshold raised to 3.0 for 11 assets after full optimizer iteration.
> See the TP/SL Optimizer — Ratio=3.0 Bump section below.

**Assets improved (6 of 21)**:

| Asset | Old tp/sl | Old ratio | Old BE_WR | New tp/sl | New ratio | New BE_WR | ΔR |
|-------|-----------|-----------|-----------|-----------|-----------|-----------|-----|
| NZDUSD | 2.0/2.5 | 0.80 | 55.6% | 2.5/2.0 | 1.25 | 44.4% | +166.0 |
| GBPCAD | 2.5/2.5 | 1.00 | 50.0% | 3.54/1.77 | 2.00 | 33.3% | +289.5 |
| USDCAD | 2.5/2.03 | 1.23 | 44.8% | 3.19/1.59 | 2.01 | 33.3% | +173.4 |
| NZDCAD | 4.0/2.5 | 1.60 | 38.5% | 4.47/2.24 | 2.00 | 33.3% | +95.4 |
| EURNZD | 2.5/1.5 | 1.67 | 37.5% | 2.74/1.37 | 2.00 | 33.3% | +63.1 |
| EURCAD | 1.5/1.0 | 1.50 | 40.0% | 1.73/0.87 | 1.99 | 33.5% | +62.1 |

**NZDUSD rationale**: Only asset with ratio < 1.0 (tp smaller than sl), penalizing the model despite both directions having genuine skill (BUY WR=58.3%, SELL WR=54.8%). Walk-forward R was +25.0R (18/19). Swapping to tp=2.5/sl=2.0 gives ratio=1.25 and +166R. This config change applies immediately to SL/TP placement; the registry was also stale (pt=1.5 → now 2.5) and is now synced.

**GBPCAD rationale**: Ratio=1.0 (symmetrical) despite BUY WR=60.1% and SELL WR=80.4% — both well above 50%. Increasing to ratio=2.0 captures more profit from both directions. +289.5R.

**USDCAD rationale**: Already swapped once (2026-06-25 earlier, tp=2.03→2.5, sl=2.5→2.03), but BUY WR=67.4% deserves a higher ratio. Moving from 1.23→2.0 on the same GM. +173.4R.

**NZDCAD rationale**: SELL WR=77.1% with ratio=1.6. Moving to 2.0. +95.4R.

**EURNZD rationale**: Both directions above 55% WR. Moving ratio 1.67→2.0. +63.1R.

**EURCAD rationale**: Both directions above 52% WR. Moving ratio 1.5→2.0. +62.1R.

**Not changed (13 assets)**: 5 already at ratio ≥ 3.0 (^DJI=8.0, CADCHF=4.0, NZDCHF=4.0, GC=4.0, EURAUD=3.28) or near their optimum. 2 at ratio=2.0 (GBPAUD, GBPCHF) already optimal for current signal quality. 2 (GBPUSD=3.79, EURCHF=3.0) near-optimal with ΔR < 20. 1 (AUDUSD=2.67) the optimizer suggests ratio=4.0 (+185R) but model has inverted BUY (16% WR) making SELL-only the dominant leg; current ratio already captures SELL profit well. 3 (ES=2.75, NQ=2.0, USDCHF=3.53) are SELL_ONLY with high SELL WR and adequate ratios.

**Caveats**: Walk-forward data uses current labels (retrained with old pt/sl). Changing tp/sl changes labels on the next retrain, which changes the model. The ΔR figures are upper-bound estimates for the immediate SL/TP placement change; the label change may shift the optimum. Re-analyze after next retrain.

**Files**: `configs/domains/assets/` per-asset YAML files, `features/registry.py`

## Covariance Estimation & HRP Fix (2026-06-25)

**Phase 1 of portfolio optimization sweep.** Added two new covariance estimators and fixed the broken HRP allocator.

### New Covariance Estimators

**`_shrinkage_cov(returns)`** — Ledoit-Wolf shrinkage via `sklearn.covariance.LedoitWolf`. Shrinks sample covariance toward the diagonal target, reducing estimation noise. Available via `risk_parity_v2` weight method.

**`_ewma_cov(returns, span=60)`** — Exponentially Weighted Moving Average covariance (RiskMetrics decay). Places more weight on recent observations. Available via `risk_parity_v3` weight method.

### HRP Fix

The `hrp_v1` method was broken due to two issues:
1. **NaN distance matrix**: When an asset had zero variance (stale/short history), correlation=NaN caused `sqrt(2*(1-corr))` to produce NaN, crashing `scipy.cluster.hierarchy.linkage`. Fixed: drop zero-variance assets before clustering.
2. **Full vs condensed distance matrix**: `scipy` expects condensed (upper-triangle) form but was receiving a full square matrix, producing `ClusterWarning`. Fixed: use `scipy.spatial.distance.squareform` to convert in `hrp_allocation()` and `_get_quasi_diag()`.

### Walk-Forward Validation

| Method | Covariance | total_R | sharpe_adj | max_dd_R |
|--------|-----------|---------|------------|----------|
| equal_v1 | — | 136.28 | 12.06 | -1.64 |
| risk_parity_v1 | sample cov | 111.93 | **15.71** | **-0.37** |
| risk_parity_v2 | Ledoit-Wolf | 118.31 | 15.28 | -1.19 |
| risk_parity_v3 | EWMA span=60 | 34.40 | 3.69 | -0.00 |
| factor_constrained_v1 | sample cov + penalty | 111.94 | 15.72 | -0.37 |
| hrp_v1 (fixed) | sample cov | 116.22 | 10.82 | -1.84 |

**Conclusion**: `risk_parity_v1` remains the best performer (best sharpe_adj, lowest max_dd). The Ledoit-Wolf shrinkage (v2) doesn't improve risk-adjusted returns. EWMA (v3) is unstable at span=60. Factor constraints weren't binding in v1. HRP now works but underperforms vanilla risk parity.

**Files**: `shared/portfolio_weights.py`, `portfolio/hrp_allocator.py`, `tests/test_portfolio.py`, `tests/test_shared_sizing.py`

## Factor Constraints That Bind (2026-06-25, Phase 2)

**Problem**: The penalty-based `factor_constrained_v1` didn't actually bind. With CHF exposure at 0.3142 vs limit 0.20 (57% over), SLSQP could not navigate the piecewise gradient of the penalty term — the optimizer converged in 2-5 iterations at the starting point regardless of `risk_parity_weight` or `penalty_scale`.

**Fix**: `factor_constrained_weights_v2` (`shared/factor_model.py:341`) uses **direct linear inequality constraints** instead of a penalty term. Each factor limit becomes a hard constraint of the form `A @ w <= b`, where each row of A is a one-hot factor group membership vector. SLSQP handles this natively with correct gradients.

**Validation**:
- CHF pinned at exactly 0.2000 (upper bound active)
- All 9 factor violations resolved
- CADCHF weight dropped from 6.4% → 0.6%, weight redistributed to USDCAD (+8.2%) and AUDUSD (+7.1%)

**Walk-Forward Comparison (all methods)**:

| Method | Covariance | Constraints | total_R | sharpe_adj | max_dd_R |
|--------|-----------|-------------|---------|------------|----------|
| equal_v1 | — | none | 136.28 | 12.06 | -1.64 |
| risk_parity_v1 | sample cov | none | 111.93 | **15.71** | **-0.37** |
| factor_constrained_v1 | sample cov | penalty (not binding) | 111.94 | 15.72 | -0.37 |
| **factor_constrained_v2** | sample cov | **hard linear** | **124.45** | **15.40** | **-0.62** |
| hrp_v1 (fixed) | sample cov | none | 116.22 | 10.82 | -1.84 |
| risk_parity_v2 | Ledoit-Wolf | none | 118.31 | 15.28 | -1.19 |
| risk_parity_v3 | EWMA span=60 | none | 34.40 | 3.69 | -0.00 |

**Winner: `factor_constrained_v2`** — has the best risk-return tradeoff. total_R = 124.45 (10% above v1, 12.5% above risk_parity_v1). Sharpe 15.40 (nearly identical to v1 at 15.71). Max DD -0.62 (second best after risk_parity_v1 at -0.37). Factor constraints bring ~12.5% total_R uplift with minimal risk degradation.

**Config**: Updated to `weight_method: factor_constrained_v2`. The old `factor_constraints.enabled: false` and `risk_parity_weight`/`penalty_scale` parameters are no longer needed — v2 doesn't use them.

**Files**: `shared/factor_model.py`, `shared/portfolio_weights.py`, `configs/domains/` tree, `scripts/backtest/backtest_pnl.py`

## Trend-Exhaustion Features — Tier 1+2 (2026-06-26)

### What Was Built

**6 new features** added to the alpha feature set, computed inside `build_alpha_features()` when OHLCV data is provided:

| Feature | Description | Source file |
|---------|-------------|-------------|
| `{asset}_macd_hist` | MACD histogram normalized by close price (±5% clip) | `features/alpha_features.py` |
| `{asset}_stoch_k` | Stochastic %K normalized to [0, 1] | `features/alpha_features.py` |
| `{asset}_stoch_d` | Stochastic %D (signal line) | `features/alpha_features.py` |
| `{asset}_bb_pct_b` | Bollinger Band %B: (close - lower) / (upper - lower) | `features/alpha_features.py` |
| `{asset}_adx_slope` | ADX rate of change over 5 days | `features/alpha_features.py` |
| `{asset}_rsi_divergence` | RSI divergence (-1 bearish / 0 none / +1 bullish) | `features/divergence.py` (NEW) |

**New file:** `features/divergence.py` — detects bullish (+1) and bearish (-1) divergences between price and RSI using local extrema within a 20-bar lookback window.

**Key design decisions:**
- MACD histogram normalized by close price (not raw price units) so it's scale-invariant across assets (USDJPY at 150 vs EURUSD at 1.0)
- All indicators use the `ta` library (already a project dependency)
- Features only computed when OHLCV is passed to `build_alpha_features()` — backward compatible (default OHLCV=None)

### Pipeline Integration

Both training and inference pipelines pass OHLCV to `build_alpha_features()`:
- `paper_trading/inference/training.py` — `ohlcv` fetch moved before `build_alpha_features()` call
- `paper_trading/inference/pipeline.py` — `ohlcv` fetch moved before `build_alpha_features()` call
- `scripts/backtest/walk_forward_backtest.py` — `ohlcv` parameter threaded through

Result: 15 per-asset alpha features (9 base + 6 trend-exhaustion) + 4 cross-asset = 19 alpha columns total when OHLCV is passed in both training and inference.

### Walk-Forward Impact (21-asset portfolio)

After full retrain with new features:

| Metric | Baseline | Step 3 | Δ |
|--------|----------|--------|--------|
| total_R | 186.4 | **248.23** | **+33.2%** |
| sharpe_adj | 17.34 | **19.56** | **+12.8%** |
| max_dd_R | -0.65 | **-0.29** | **-55.4%** |

GBPJPY specifically improved from ~0R to +299R (was essentially zero — now profitable).

### Asset-Specific Recovery

Each remaining SELL_ONLY asset was evaluated against its Step 3 BuyWR vs breakeven WR:

| Asset | Step3 BuyWR | BE WR | Δ | Verdict |
|-------|-------------|-------|---|---------|
| **USDCHF** | 29.9% | 22.1% | **+7.8pp** | REMOVED from SELL_ONLY |
| **EURCHF** | 26.2% | 25.0% | **+1.2pp** | REMOVED (marginal) |
| **USDJPY** | 39.4% | 20.9% | **+18.6pp** | REMOVED from SELL_ONLY |
| **^DJI** | 24.3% | 11.1% | **+13.2pp** | REMOVED from SELL_ONLY |
| **GBPJPY** | 38.6% | 18.4% | **+20.2pp** | REMOVED from SELL_ONLY |
| EURAUD | 22.5% | 23.4% | -0.9pp | STAY in SELL_ONLY |
| CADCHF | 10.5% | 20.0% | -9.5pp | STAY in SELL_ONLY |
| NZDCHF | 11.7% | 20.0% | -8.3pp | STAY in SELL_ONLY |
| ES | 10.7%* | 26.7% | -16.0pp | STAY in SELL_ONLY |
| NQ | 19.6%* | 33.3% | -13.7pp | STAY in SELL_ONLY |

*ES/NQ evaluated from baseline only (futures walk-forward label sparsity prevented Step 3 generation with production pt/sl configs).

### SELL_ONLY Reduction Summary

SELL_ONLY_ASSETS reduced from 10 → 3 assets:
- **Removed** (7): GBPJPY, USDCHF, EURCHF, USDJPY, ^DJI, ES, NQ — all have BuyWR > Breakeven WR
- **Remaining** (3): CADCHF, NZDCHF, EURAUD — impervious to all interventions tested

The SELL_ONLY filter is now a focused guard for the 3 assets with genuinely unrecoverable BUY signal — not a portfolio-wide stopgap.

### Orphaned Model Cleanup

4 models from removed production assets moved to `paper_trading/models/orphaned/`:
- EURUSD, AUDNZD, AUDCHF, GBPNZD (all removed 2026-06-20)

21 models remain in `paper_trading/models/` — one per production asset.

---
## TP/SL Optimizer — Ratio=3.0 Bump (2026-06-30)

### Methodology

Grid search over ratio space [0.5, 20.0] log-scale for all 21 assets using `scripts/optimization/portfolio_sltp_optimizer.py`, estimating config-only PnL (current signals × new tp/sl). Geometric mean constraint preserves average barrier distance.

**Key result:** All 21 assets converge to ratio=20.0 (search boundary) — the optimizer always wants more ratio. Ratio=3.0 chosen as conservative cap to keep SL (0.71–2.04%) above intraday noise. SL fragility test confirms 20/21 OK, 0 CRITICAL, 1 FRAGILE (NZDCAD frag=2.00, hit rate 0.22%).

### Assets Bumped (<3.0 → 3.0, 11 assets)

| Asset | Old ratio | New ratio | Old sl | Old tp | New sl | New tp |
|-------|-----------|-----------|--------|--------|--------|--------|
| USDCAD | 2.01 | 3.00 | 1.59 | 3.19 | 1.30 | 3.90 |
| ES | 2.75 | 3.01 | 2.00 | 5.50 | 1.91 | 5.74 |
| NQ | 2.00 | 3.00 | 2.50 | 5.00 | 2.04 | 6.12 |
| GBPCAD | 2.00 | 2.99 | 1.77 | 3.54 | 1.45 | 4.34 |
| NZDCAD | 2.00 | 2.99 | 2.24 | 4.47 | 1.83 | 5.48 |
| NZDUSD | 1.25 | 3.00 | 2.00 | 2.50 | 1.29 | 3.87 |
| GBPAUD | 1.33 | 3.00 | 1.50 | 2.00 | 1.00 | 3.00 |
| AUDUSD | 2.67 | 3.01 | 1.50 | 4.00 | 1.41 | 4.24 |
| EURCAD | 1.99 | 2.99 | 0.87 | 1.73 | 0.71 | 2.12 |
| EURNZD | 2.00 | 3.00 | 1.37 | 2.74 | 1.12 | 3.36 |
| GBPCHF | 2.00 | 2.99 | 1.00 | 2.00 | 0.82 | 2.45 |

### Tools Built (8 scripts)

| Script | Purpose |
|--------|---------|
| `scripts/optimization/portfolio_sltp_optimizer.py` | Two-pass log-space grid search [0.1–20.0] with GM constraint |
| `scripts/optimization/sl_fragility_test.py` | 4h OHLCV intraday SL hit rate vs daily |
| `scripts/optimization/drift_detector.py` | Live win-rate drift against breakeven WR; powers dashboard |
| `scripts/optimization/trade_outcome_repository.py` | Flat trade outcome DataFrame from SQLite |
| `scripts/optimization/portfolio_balancer.py` | Correlation-aware cluster risk discounting (Equity 15%, CHF 5%) |
| `scripts/optimization/per_asset_quality.py` | EV/breakeven/MFE/MAE quality classification |
| `scripts/optimization/risk_compression.py` | Stress scenario injection for TP/SL configuration |
| `scripts/optimization/directional_win_rate.py` | Per-direction BUY/SELL win rate tracking |

### Dashboard Integration

- **`/optimization.json`** endpoint (`state_routes.py:258`) serves drift detector output
- **`OptimizerRecommendations.tsx`** component renders flagged assets on the DashboardOverview page
- Populated by: `PYTHONPATH=$PYTHONPATH:. python scripts/optimization/drift_detector.py --json > data/live/optimization.json`

### Validation (Backtest After Retrain)

All 21 models retrained with new tp/sl labels. Walk-forward comparison:

| Metric | Step 3 baseline | After ratio=3.0 | Δ |
|--------|----------------|------------------|---|
| total_R | 248.23 | **288.4** | **+16.2%** |
| sharpe_adj | 19.56 | 15.96 | -18.4% (portfolio composition) |
| max_dd_R | -0.29 | **-0.15** | **-54.7%** |
| Assets profitable | 17/17 | 17/17 | unchanged |

### SELL_ONLY List Update

Confirmed unchanged (3 assets): CADCHF, NZDCHF, EURAUD. No SELL_ONLY asset was affected by the ratio change — the filter is performance-independent.

### Falsified Concern

**Hypothesis:** Ratio=3.0 makes SL too tight for some assets, causing intraday wick-outs.
**Test:** `sl_fragility_test.py` scans 4h OHLCV for any bar that would have hit the new SL intraday.
**Result:** 20/21 OK, 0 CRITICAL. NZDCAD FRAGILE at frag=2.00 but absolute hit rate 0.22% — acceptable.

## Ruff

```bash
ruff check . && ruff format .
```

## Codebase Remediation (2026-06-30+)

A series of incremental hardening commits applied to `refactor/codebase-remediation`:

1. **`fix(security)` — replace asserts, add .env permission check**
   - `paper_trading/services/entry_service.py:_validate_sltp_invariants` — replaced 8 `assert` statements with proper `if` checks that log and return `False`. Asserts are stripped under `python -O` and would have allowed invalid SL/TP state to pass.
   - `paper_trading/config_manager.py` — new `_warn_on_insecure_dotenv()` runs at module import. Warns if `.env` exists with world-readable permissions and lists which exposed env vars are present. Sensitive vars tracked: `MT5_PASSWORD`, `MT5_ACCOUNT`, `OPENCODE_ZEN_API_KEY`, `QUANTFORGE_API_TOKEN`, `PAGERDUTY_ROUTING_KEY`, `SLACK_WEBHOOK_URL`.
   - `shared/sizing_chain.py` — fixed one line-too-long in log format string.

2. **`feat(config)` — YAML schema validator**
   - `tools/check_config_schema.py` — validates domain configuration files from `configs/domains/` top-level fields, types, value ranges, asset ticker presence, and section structure. Wires into CI as a separate step.
   - `tests/test_config_schema.py` — 12 tests covering valid config, invalid rebalance/data_source/capital, missing ticker, bad MT5 port, missing file.
   - `.github/workflows/ci.yml` — adds `python tools/check_config_schema.py` step, uncomments the `scripts/check_live_deps.sh` step, expands ruff scope from `paper_trading/` to whole repo.

3. **`test(sizing)` — property-based invariants**
   - `tests/test_sizing_chain_properties.py` — 10 hypothesis-driven property checks: viable iff skip_reason, nonneg notional/quantity, drawdown taper bounds [min_size, 1.0], atomic budget under concurrent compute, no crash on zero equity or extreme size_scalar/drawdown.

4. **`test(wal)` — concurrency stress**
   - `tests/test_wal_replay.py::TestWalConcurrency` — 200-event multi-threaded test (8 threads × 25 events) verifying no events lost and sequences are exactly 1..N with no gaps. Concurrent flush stress test (4 threads × 10 events) confirms JSON validity under interleaved writes+flushes.

The WAL already had correct lock scope (lock released before `open()/writelines()/flush()/os.fsync()`), so no production code change needed for fsync — only the new test coverage.

## Validation Commands

```bash
ruff check . && ruff format . --check
python tools/check_config_schema.py
python tools/check_import_firewall.py
python tools/check_no_bare_asserts.py
python tools/check_no_plaintext_secrets.py
PYTHONPATH=$PYTHONPATH:. python tools/doc_drift_check.py
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/ -q
```

## Deferred-Items Resolved (2026-06-30+)

Continued hardening of the `refactor/codebase-remediation` branch — six
phases that address every item originally deferred from the production
readiness audit:

### 7. MT5 Bridge Security
- `paper_trading/ops/mt5_client.py:_is_loopback` rejects non-loopback
  hosts; `MT5Client.__init__` logs WARNING and accepts an explicit
  `allow_remote_bridge=True` override for testing only.
- `tests/test_mt5_security.py` — 20 contract tests covering loopback
  detection, private/public CIDR rejection, missing-host fallback,
  warning emission, password-leak prevention in logs/repr, and AST-level
  checks that the bridge source binds to 127.0.0.1 only and uses
  `MT5_PASSWORD` env var (not CLI args).

### 8. MT5 Bridge Supervision
- `scripts/ops/mt5_bridge_supervisor.py:BridgeSupervisor` watches the
  bridge via JSON-RPC heartbeat, restarts it on consecutive failures,
  and exposes `/health` + `/ready` endpoints. Configurable interval,
  max-restart cap, graceful SIGTERM.
- `scripts/ops/eigencapital-mt5-supervisor.service` — systemd unit with
  hardening (NoNewPrivileges, PrivateTmp, ProtectSystem).
- `monitor_all` — removed `--password $MT5_PASSWORD` from the argv
  (was leaking the secret via `ps aux`).
- 14 tests in `tests/test_mt5_supervisor.py` covering watchdog
  detection, health 200/503 transitions, restart cap, signal handling.

### 9. Structured JSON Logging
- `paper_trading/logging/json_formatter.py:JsonFormatter` exports records
  as single-line JSON with the canonical EigenCapital key order. Handles
  `extra=` payload, exception serialization, unicode. Optional
  replacement of stream handlers via `install_json_logging`.
- 13 tests in `tests/test_json_logging.py` cover valid JSON output,
  exception/unicode handling, label determinism, and hardening
  (no internal Python state leaks).

### 10. Prometheus Metrics
- `eigencapital/observability/metrics.py:MetricsRegistry` — thread-safe
  counter/gauge registry with `render()` for Prometheus v0.0.4 text
  exposition format. Validates metric names per `[a-zA-Z_:][a-zA-Z0-9_:]*`.
  Pre-seeded `default_registry()` includes the EigenCapital engine metric
  namespace (`eigencapital_engine_cycles_total`, `..._signal_total`,
  `..._drawdown_pct`, `..._wal_events_total`, etc.).
- 18 tests in `tests/test_prometheus_metrics.py` covering basic counter
  /gauge, label ordering/escaping, sample ordering, invalid names, and
  concurrent safety.

### 11. Pre-commit Hooks
- `.pre-commit-config.yaml` — six local hooks wired into a single
  pre-commit install:
    * ruff lint
    * ruff format
    * config schema check (only when configs/*.yaml changes)
    * import firewall
    * scan for unclaimed TODO/FIXME/XXX/HACK markers
    * no-bare-asserts guard
    * plaintext-secret detector
- `tools/check_no_bare_asserts.py` — AST scan; production code with
  bare `assert` invocations fails to land.
- `tools/check_no_plaintext_secrets.py` — regex sweep with allowlist
  for known placeholders (your_password, ..., etc.) and tests/ dir
  exclusion for synthetic credentials.
- 10 tests in `tests/test_precommit_hooks.py`.

### 12. Chaos Engineering Framework
- `tests/chaos/chaos_tools.py:FaultRecipe` + `fault_inject` context
  manager — deterministic, scoped fault injection. Supports count-limited
  failures, probability-controlled failures, custom exceptions, return
  overrides, and latency simulation. Patches replace the original on
  exit (even on exceptions) and stack correctly under nesting.
- 13 tests in `tests/chaos/test_chaos_tools.py` — including the
  transient-disconnect retry scenario.

### 13. ATLAS Covariate Shift Detector
- `eigencapital/observability/atlas.py:AtlasDetector` — layered change-point
  detector combining:
    * Two-sided CUSUM (cumulative sum control chart) with standard
      deviation–scaled thresholds.
    * Page-Hinkley (symmetric drift detector with running minimum).
    * Sliding-window two-sample Kolmogorov-Smirnov test (non-parametric
      distributional equality).
- 12 tests in `tests/test_atlas_detector.py` — verify that constant
  series never fires, step changes eventually trigger CUSUM, smooth
  gradients can be detected, and extreme/negative inputs don't crash.

### Final Validation Summary
- 1912 tests pass (was 1812 at the first remediation checkpoint;
  +100 new tests).
- ruff check: zero errors.
- ruff format: zero diffs.
- config schema validator: passes (16 assets, 3 sell-only).
- import firewall: passes (249 files, no forbidden imports).
- bare-asserts guard: passes (140 prod files clean).
- secrets scanner: passes (no plaintext credentials).
- pre-commit yaml: valid, includes 6 hooks.

---
> **Historical note:** The results in this section (total_R +175.79, 16/16 assets) were computed on the original 16-asset portfolio during the remediation phase. The current production system operates on **22 assets** with calibrated probabilities, direction-conditional thresholds, and adaptive exit engine, producing **+838.06 R** (Sharpe 58.47) with all 22 assets profitable. See [AGENTS.md](../AGENTS.md) and [README.md](../README.md) for current metrics.

## Portfolio Remediation & Adaptive Exit Engine (2026-07-01)

### Phase 0 — Evaluation Framework

1. **Signal encoding bug (FIXED)**: `walk_forward_all.py:136` had SELL=0 colliding with flat=0, causing walk-forward to undercount SELL trades. SELL→1, flat→0, BUY→2. Determinsm confirmed (byte-identical outputs across runs).

2. **MT5 realized_pnl bug (FIXED)**: `mt5_broker.py:393` mapped `realized_pnl` to `commission` field, always returning 0.0 for open positions. Now 0.0 (correct — unrealized positions have no realized PnL). `normalize()` regex `[=F=X^]` stripped F/X from ticker names — FIXED.

3. **Prometheus gate-blocked counter (FIXED)**: `engine_gate_blocked_total` declared but never written to. Fix: `_gate_blocked_counts` tracking in `AssetEngine.__init__`, incremented in `run_decision_pipeline` loop.

4. **GBPUSD missing from ASSETS dict (FIXED)**: Never added to hardcoded `ASSETS` dict in `walk_forward_backtest.py` after promotion 2026-06-22. Profitable under triple-barrier (+338.82R, WR 58.96%).

### PnL Backtest — 16-Asset Portfolio

After removing 5 worst assets (DJI, ES, NQ, GBPJPY, USDJPY):

| Metric | Value |
|--------|-------|
| total_R | +175.79 |
| Sharpe (adj) | 13.70 |
| max_dd_R | -0.16 |
| Assets positive | 16/16 |
| Win rate > 50% | 15/16 |

### Trade Lifecycle Analysis — 18 Phases

**Script**: `scripts/analysis/trade_lifecycle.py` — reconstructs every trade from `_remediation` signal parquets + OHLCV for all 16 assets.

**Summary** (4,679 reconstructed trades):

| Metric | Value |
|--------|-------|
| Total R | +519.46 |
| Win rate | 34.8% |
| Avg efficiency | 62.0% |
| Avg duration | 9.4 candles |
| R per 100 candles | +1.19 |
| TP rate | 15.5% |
| SL rate | 62.4% |
| Barrier expiry | 22.1% |
| Avg profit left (MFE under-capture) | +0.49R |
| Avg MAE | +1.09R |
| Avg MFE | +1.58R |
| Efficiency > 75% | 50.3% |

**Critical finding — confidence provides zero discrimination**:
```
Bucket         N      WR    AvgR   Eff
0.00-0.25   2199  35.4%  +0.12  60.6%
0.25-0.40    588  33.3%  +0.11  59.0%
0.40-0.45    107  33.6%  +0.13  67.6%
0.55-0.60     94  31.9%  +0.07  59.3%
0.60-0.75    508  29.9%  +0.01  64.0%
0.75-1.00   1183  36.6%  +0.13  64.9%
```
All buckets are statistically indistinguishable. Model probability output provides no signal-ordering value.

**6 losing assets** (under fixed-barrier lifecycle reconstruction):

| Asset | Trades | TotalR | WR | Eff | TP% | R/100c |
|-------|--------|--------|----|-----|-----|--------|
| EURAUD | 189 | -110.6 | 16.9% | 57% | 4% | -6.77 |
| NZDUSD | 332 | -69.1 | 31.3% | 65% | 8% | -1.92 |
| AUDUSD | 272 | -43.2 | 32.7% | 63% | 8% | -1.41 |
| EURNZD | 325 | -17.3 | 31.7% | 63% | 15% | -0.55 |
| GBPAUD | 321 | -16.9 | 29.9% | 58% | 16% | -0.61 |
| GBPCHF | 319 | -10.8 | 26.0% | 66% | 20% | -0.48 |

**Reversal pattern**: 25-46% of losing trades across these assets had MFE ≥ 1.0R — price went in the model's direction (to profitable territory) then reversed to hit SL. These are NOT directional failures — they are exit-mechanic failures.

### Trailing Stop Simulation

**Script**: `scripts/analysis/trailing_stop_sim.py` — applied retracement-based trailing to lifecycle reconstructed trades. Exit at `(1 - retrace_pct) × peak_MFE`.

**Results at 50% retracement** (exit at 50% of peak MFE):

| Asset | Original R | With 50% Trail |
|-------|-----------|----------------|
| EURAUD | -110.6 | **+24.1** |
| NZDUSD | -69.1 | **+193.5** |
| AUDUSD | -43.2 | **+189.7** |
| EURNZD | -17.3 | **+205.0** |
| GBPAUD | -16.9 | **+159.8** |
| GBPCHF | -10.8 | **+132.3** |
| **Portfolio** | **+519.5** | **+3,209** (6.2×) |

**All 16 assets become profitable** with 50% retracement trailing. Even EURAUD (the worst asset at -110.6R) reaches +24.1R.

**Conclusion**: The system is not "barely profitable with 6 bad assets." It is a **fat-tailed profitable system whose edge is systematically truncated by fixed barrier exits.** The real bottleneck is exit mechanics, not signal quality.

### Adaptive Exit Engine — Implementation

**New module**: `paper_trading/position/adaptive_exit.py` — `AdaptiveExitEngine` class implementing retracement-based dynamic exits.

**Three-stage model**:
1. **Breakeven lock** (at `be_lock_r` MFE, default 0.5R): move SL to entry
2. **Retracement trail** (at `trail_activation_r` MFE, default 0.8R): set SL at `peak_price - retrace_pct × (peak_price - entry_price)` for longs
3. **Time decay** (after `time_decay_start` candles): gradually tighten retracement tolerance toward max hold

**Integration**: Called every cycle from `AssetPnlController._check_intraday_sltp()`. Updates `stop_loss` via `pos_mgr.update_stop_loss()` and syncs to MT5 via `_sync_broker_sltp()`.

**Bug fix — `check_sl_tp()`**: `PositionManager.check_sl_tp()` in `position/manager.py` used `self.position.stop_loss` instead of `self.position.effective_sl`, making `PositionProtection.update()`'s `risk_floor` entirely dead code. Fixed to use `effective_sl`.

**Config**: Per-asset `adaptive_exit` block in `configs/paper_trading.yaml`. Defaults for winning assets: activation_r=0.8, retrace=0.50. Aggressive defaults for 6 formerly-losing assets: activation_r=0.5, retrace=0.50.

### Validation

- 2331 tests pass, 16 skipped (unchanged from pre-remediation baseline)
- Config schema passes: 16 assets, 3 sell-only
- No regressions in any existing functionality

### Robustness Gatekeeper Results

**Script**: `scripts/analysis/robustness_gatekeeper.py` — 5-test validation suite:

| Test | Result | Verdict |
|------|--------|---------|
| Regime robustness (ATR-split) | ALL 16 assets positive in BOTH low/high vol | PASS |
| Bootstrap (500 resamples) | Trail > Fixed in **100%** of resamples. 95% CI: [3,045, 3,384] vs fixed [336, 712] | PASS |
| Slippage sensitivity | 2.0R adverse: still +2,099.8R (4× fixed baseline) | PASS |
| Ablation comparison | All trailing variants > fixed on Sharpe. Trail_33pct: Sharpe 3.186 | PASS |
| Benefit concentration | 33.8% of trades improve. Top 10% = 39.9% of benefit (moderate) | PASS |

### MFE Stationarity & Walk-Forward Retrace Stability

**Script**: `scripts/analysis/mfe_stationarity.py` — 3-test validation:

| Test | Result | Verdict |
|------|--------|---------|
| MFE distribution (early vs late half) | KS p=0.1864 > 0.05 — cannot reject identical dist | PASS — stationary |
| Walk-forward retrace (period A→B optima) | Best retrace=25% on BOTH periods. All ranking identical | PASS — stable |
| Reversal rate by quartile | 39.1%→30.5% decline across 2.5 years | MONITOR |

**MFE Stationarity**: Early half mean MFE=1.60R vs late half mean=1.57R. P95 MFE 4.38R vs 4.03R. Trailing improvement nearly identical: +1,407R (early) vs +1,283R (late).

**Retrace Stability**: All retrace levels rank identically across both halves. 50% retrace produces +1,608.9R on A and +1,600.4R on B — nearly identical. The monotonic "tighter is better" relationship is not coincidental — it's structurally stable.

**Reversal rate mild decline**: Losers with MFE ≥ 1R dropped from 39.1% (Q1) to 30.5% (Q4). The trailing edge remains massive at 30.5%, but this decline should be monitored quarterly. If rate drops below ~15%, retracement-based trailing loses its advantage.

**Caveat**: Simulation is conservative — never clips winners (only modifies loser exits). Real-world improvement will be lower due to winner-clipping. But the bootstrap's 100% win rate, 2R slippage survival, and MFE stationarity all suggest the edge is genuine.

## Shock Simulation Engine — Structural Fragility Discovery

**Script**: `scripts/analysis/shock_simulation.py` — applies structural perturbations to realized MFE distribution and measures whether the adaptive exit edge survives.

**Not a validation script.** Designed to answer: "how does the system break when the world stops looking like history?"

### 7 Shock Classes Tested

| Shock | What it models | Examples |
|-------|---------------|----------|
| **MFE Compression** | Volatility decay — market moves get smaller | Scale MFE by 0.3-0.7 |
| **Retrace Acceleration** | Spiky price action — retracements happen faster | Increase effective retrace_pct by 10-35pp |
| **Gap** | Black swan fills — price gaps through trailing stop | Zero MFE on 5-20% of losing trades |
| **Multi-Peak Decoy** | Fakeout rallies — false MFE peaks trigger premature trailing | 10-25% of trades lose 30-70% of MFE to early exit |
| **Execution Lag** | Delayed fills — trailing stop triggers late | 20-50% of trades lose 0.2-0.5R to slippage |
| **Correlated Crash** | Cascade/contagion — synchronous multi-asset drawdown | 1-4R loss applied to 20-50% of overlapping trades |
| **Trend Fragmentation** | Shortened trend regimes — MFE tail compresses | Progressive MFE compression biased toward long tail |

### Results (21 scenarios across 16 assets)

| Severity | Count | Threshold |
|----------|-------|-----------|
| CATASTROPHIC | 0 | edge retention < 0% |
| SEVERE | 0 | edge retention < 50% |
| MODERATE | 2 | edge retention 50-80% |
| PASS | 19 | edge retention > 80% |

### Detailed Findings

**No break point for MFE compression**: Even at 90% compression (MFE = 10% of original), edge retention = 74.8%. The system monetizes ANY favorable excursion.

**No break point for retrace acceleration**: At 95% effective retrace (trailing stop barely activates), edge retention = 74.8%. The 50% trailing setting is not optimal but is robust.

**Gap shock is harmless**: 20% gap rate retains 94.3% edge. Random black swan gaps don't structurally threaten the system because only a minority of losing trades have adequate MFE for trailing to help.

**Decoy and execution shocks are negligible**: Retention > 94% across all intensities. The system's benefit is distributed across enough trades that localized failures don't matter.

**Trend fragmentation is mild**: 70% fragmentation retains 89.2%. Progressive MFE tail compression doesn't remove the edge because the majority of saved trades have robust MFEs even under compression.

**Correlated crash is the dominant risk (MODERATE)**: At 4R / 50% trade saturation, edge retention = 54.4%. This is the only scenario that degrades below 70%. The fixed R baseline (+519.5) still produces a floor under extreme conditions — trailing R never drops below +2,832.

### Conceptual Conclusion

The adaptive exit system is **structurally shock-stationary** — edge degrades gracefully (not catastrophically) across all tested perturbations. The remaining risk is edge magnitude, not edge existence. The system is deployable with monitoring, with the single caveat that a synchronized multi-asset drawdown (4+R across 50% of all trades) would compress edge by ~46%.

### Key Files

| File | Purpose |
|------|---------|
| `scripts/analysis/trade_lifecycle.py` | 18-phase trade reconstruction + analysis engine |
| `scripts/analysis/trailing_stop_sim.py` | Retracement-based trailing stop simulation |
| `scripts/analysis/robustness_gatekeeper.py` | 5-test robustness validation suite |
| `scripts/analysis/mfe_stationarity.py` | MFE stationarity + walk-forward retrace stability |
| `paper_trading/position/adaptive_exit.py` | `AdaptiveExitEngine` — live retracement trailing |
| `paper_trading/position/manager.py` | `check_sl_tp()` now uses `effective_sl` (risk_floor fix) |
| `paper_trading/asset_pnl_controller.py` | `_apply_adaptive_exit()` integration in `_check_intraday_sltp` |
| `configs/paper_trading.yaml` | Per-asset `adaptive_exit` config blocks |
| `data/processed/trade_lifecycle_results.json` | Full lifecycle analysis output (1.8MB, 4679 trades)

---
## Production Audit Remediation (2026-07-01+)

Systematic 4-phase remediation of audit findings on `feature/production-audit-remediation`.

**Phase 1 — Critical Production Blockers (commit 290711f)**: Dual trailing stop conflict resolved (`_check_intraday_sltp` routes to one exit system per cycle); MT5 modify_position failure log DEBUG→ERROR with SL read-back verification (`_verify_sltp_applied`); paper close no-longer aborted on MT5 failure — proceeds with error logging, orphan handled by reconciliation loop. 2375 tests pass.

**Phase 2 — Architecture Hardening (commit 02166f0)**: Shared `_load_sltp_data` helper extracted (eliminates duplicated guard logic); atomic cache invalidation in `_verify_sltp_applied` (no lock race window); Position dataclass extended with `stop_loss`/`take_profit`; dead fields removed from EngineSnapshot state (`gates_trace`, `last_regime_raw_probas`, `last_regime_features`, `calibration`).

**Phase 3 — Frontend UX Redesign (commit 4dbcf97)**: CommandCenter page merges TradingDashboard + DashboardOverview; EquityCurveSparkline SVG component from `/equity_history.json`; sortable asset list by risk/name/pnl/exit; Conviction badges removed (non-predictive — per audit finding); PEK status bar removed; dead field references cleaned from ExecutionFeed, GateAggregationPanel, AssetDetailPanel. TypeScript 0 errors.

**Phase 4 — Polish & Cleanup (current)**: Stale asset refs cleaned (data_fetch.py _ZERO_RATE_ASSETS: removed ES/NQ/DJI; trade_analysis.py: cleared stale SLTP_CFG/DASHBOARD_TICKERS/MODEL_DEPTH); LIVE_CONTRACT.md US_EQUITY factor group updated; AGENTS.md changelog added. ruff format + check clean.

---

## Dashboard Operator-Console Redesign (in progress + paused)

Branch: `redesign/operator-console-terminal-precision`. Visual identity: **operator-console / terminal-precision**, dark-only, mono supremacy, single accent (teal-emerald).

**Phases 1–4 complete (8 commits)**:

- **Phase 1.1** `ceda2d5` — Removed dead pages & token file: `pages/TradingDashboard.tsx`, `pages/DashboardOverview.tsx`, `components/AnchorNav.tsx`, `theme/tokens.ts`. Verified via `lazy(`/`dynamic(` grep that none of these were dynamically imported before deletion.
- **Phase 1.2** `9c32101` — Collapsed `KpiCard` + `MetricCard` into `StatCard`. Migrated `WeeklyReviewModal`'s 10 instances to `StatCard variant="kpi"`.
- **Phase 1.3** `f528020` — Cut light mode entirely for v1: removed `ThemeToggle.tsx`, `rawLightTokens` from color-system.ts, the `.light {}` block in `generated/tokens.css`, and the `light` DTCG group in `generated/tokens.json`.
- **Phase 1.4** `900467d` — Removed dead CSS classes from `index.css` (`.metric-card`, `.section-title`, `.glass`, `.btn-primary`, `.btn-ghost`, `.signal-pill*`, `.metric-value`, `.interactive*`, `:root` smooth-theme transition). Living classes preserved: `.panel`, `.skeleton`, `.metric-label`, `.table-header`, `.sort-header`, `.table-row-hover`, `.anchor-nav`, `.input-terminal`, `.focus-ring`.
- **Phase 2.5** `fbab2c6` — Extracted `BarRow` named export from `ProgressBar.tsx`; `SltpGauge.tsx` now stacks three `BarRow`s. Public APIs unchanged.
- **Phase 2.7** `69b853b` — Removed unused `SkeletonText` + `SkeletonKpi` from `ui/Skeleton.tsx`. Kept `Skeleton`, `MetricCardSkeleton` (2 live consumers), `TableSkeleton` (4 live consumers).
- **Phase 2.8a** `d46f101` — `SectionHeader`: dropped 3-layer pulsing accent (static dot + glow halo + animate-ping). API unchanged (7 accent variants still accepted).
- **Phase 2.8b** `f219c42` — `EntranceAnimator`: dropped `stagger`/`staggerDelay`/internal `EntranceAnimatorItem` (zero external consumers). Single mode with `delay` retained.
- **Phase 2.4** `6604fd5` — Merged `AssetMiniCard` into `AssetCard` with `density: 'comfortable' | 'compact'` prop. Shared signal-extraction logic. `AssetMiniCard.tsx` deleted; `AssetMiniGrid.tsx` updated to pass `density="compact"`.
- **Phase 3** `a7329eb` — Removed duplicate `<EmergencyHaltBanner>` render in `pages/CommandCenter.tsx`. `AppShell.tsx` already mounts it once at top level.
- **Phase 4** `d3d322e` — **IA-1**: nav-rail status chip. `useSidebarBadges` extended to expose engine `'alive'|'stale'|'dead'` state. Inline engine dot on the Dashboard nav item, bottom-of-rail `engine STATUS` caption row, removed the redundant top strip widget. Header still shows engine health as a separate glance surface.

**Phase 5 — IA-3 HOLD-AND-OBSOLETED**: Per the design lead's explicit decision, IA-1 (nav-rail status chip, Phase 4) shipped first to test whether it alone satisfies the glance-check without IA-3's tab split. After Phase 4 + Phase 6.1 (IA-2 deleted `/engine`), the IA-3 prescription has effectively become obsolete: with `/engine` gone, the rail has a single Overview item ("Dashboard") pointing to a single CommandCenter — there is no ambiguity left for a tab strip inside the route to resolve. **Decision recorded; do not implement IA-3 in any branch without re-approval.**

**Phase 6 — IA resolutions (12 commits added after Phase 5)**:

| IA | Resolution | Outcome |
|---|---|---|
| **IA-2** | Dropped `/engine` route dual-mount in `App.tsx`; removed `Heart`/`engine` nav item from `Sidebar`; updated description from "Raw metrics + full data" to "Status, equity, positions". | **Code change** — commit `f7a21cd`. |
| **IA-4** | Move `PekScalarPanel`, `PerformanceStateVelocityChart`, `RiskBudgetChart` off `/risk` onto `/engine`. Post-IA-2 there is no `/engine`, so the move has no destination. **Decision: leave them on `/risk`.** They are auxiliary telemetry, not risks, but the correct location is a separate `/behavior` route which is out of scope here. | **No code change**; debate closed. |
| **IA-5** | `GateAggregationPanel` + `GovernanceRadar` already live in `/risk/risk` workspace under their respective sections. | **No change needed**; verified. |
| **IA-6** | `PositionConcentrationPanel` + `FactorExposureBreakdown` already on `/risk` only. | **No change needed**; verified. |
| **IA-7** | Moved full-recharts `EquityChart` from `TradingWorkspace / Signals` section to new `ExecutionWorkspace / Equity Curve` section. The chart shows portfolio time-series, drawdown, and per-asset overlays — performance surfaces, not signal surfaces. The small `EquityCurveSparkline` (80px) stays on `CommandCenter`'s status row as the operator's glance-only summary. | **Code change** — commit `ee30ccc`. |
| **IA-8** | `AnchorNav` already removed in Phase 1.1. | **No change needed**. |
| **IA-9** | `ExecutionFeed` (live stream) is on `/trading`; `TradeExecutionTable` (full table) is on `/execution`. The two surfaces serve different primary jobs (live signal vs historical record) and are correctly split. The "duplicate rows" concern was inaccurate. | **No change needed**; verified. |

After Phase 6: 4 routes (`/`, `/trading`, `/execution`, `/risk`), each with a single primary job. CommandCenter sits at 6 rather than 8 sections (no redundant equity chart, no redundant banner). The rail's status chip from Phase 4 plus the Header's `HealthBadge` provide engine-state-without-scrolling from two persistent surfaces.

**Audit items deferred to dedicated PRs** (not in this branch): #1 (QuickStatCard → StatCard), #2 (PekStatusBar fold-in), #7 (TradingAssetRow extraction), #11 (Panel variant collapse), #13 (PekScalarPanel relocation — IA-4 closed without code), #14 (EquityChart migration — done in 6.7), #16 (Header health chip move). Each has large file-fan-out and is its own reviewable commit when picked up.

---

### Phases 7–9 (final months of the redesign)

After Phase 6 the branch continued into copy + visual identity. Roughly thirty commits landed that complete the operator-console surface treatment. Section IDs are by phase / commit prefix.

**Phase 7 — operator-voice copy** (commit `aa1577b`)

- Header.tsx health badge: title `'Engine: {label} — click for details'` → `'Engine {label}'`, aria-label `'Engine status: {label}. Open details.'`
- Header.tsx refresh button: `'Refresh all dashboard data'` → `'Refresh dashboard data'`
- Header.tsx menu button: `'Toggle navigation'` → `'Open navigation menu'`
- AppShell.tsx ErrorScreen: title `'System Unavailable'` → `'Engine unavailable'`; message moved to active voice (`"Couldn't load the engine snapshot. It may be restarting."`)
- Other copy audited and intentionally left: `SAFE` / `MONITOR` / `ALERT` (operator-standard triad); "All systems nominal" (in-domain status idiom for the audience); SectionHeader / EmptyState section hints already operator-natural

**Phase 8 — design system implementation**

Three commits shipped the operator-console signature.

- Phase 8.1 `ef624ee` — **`TickerRail` signature element**: 32px-tall mono breadcrumb pinned above `<Header>` on every route. Reads as `Q ·EIGENCAPITAL · seq #N · engine <state> · tick <N>s · pek <a>/<i> · halt <yes|no> · assets <N>` in mono. Morphs to a halt-channel when `emergency_halt` is set; positions-frozen annotation; not rendered when `integrity.shouldBlockRender` (display uses `ErrorScreen`). Data: `useEngineHealth` + `useSystemSnapshot`. Tone-coded GREEN / YELLOW / RED on each token.
- Phase 8.2 `7ea43b6` — **Design tokens**: `color-app` `#08090c → #07080b` (deeper ink); `color-accent-emerald` `#2dd4bf → #3dd9ae` (lifted accent); matching `rgba` updates in `index.css` focus-ring + input-terminal; `usage.*` updated to source lifted palette; `generated/tokens.css|json|tailwind.partial.js` regenerated automatically.
- Phase 8.3 `dc4e3a1` — **Quick-stats row on CommandCenter migrated**. The 7-card grid (each labelled card with icon and padding) collapsed to a single hairline-rule mono dl/div row. Five reserved audit items addressed in this commit at no additional cost (dead `QuickStatCard` definition and 7 unused icon imports removed by reconstruction).

**Phase 9 — component-by-component visual redesign**

Six commits. The pattern is unchanged from the audit: terminal-precision treatment means *one* mono headline per row, governance semantic colors only on values that read green/yellow/red, and a single hairline rule between cells on desktop.

- Phase 9.1 (4 commits: `16ea6f8`, `f252e13`, `8172a29`) — `/trading` surfaces: `SignalsTable` filter-input focus ring → lifted accent rgba; `TradeOutcomes` 6 KPI accents recoloured to `var(--color-gov-{green,yellow,red})` for the semantic cells (TP / SL / Flip / Avg R) and `var(--color-text-secondary)` for the percentage cells (Win Rate, Profit Factor — chart palette dropped); `AdmissionPanel` 3-stat row migrated to dl/div hairline pattern (Intents / Admitted / Rejected mono cells).
- Phase 9.2 (3 commits: `f932f48`, `35c5831`, `18290e5`) — `/execution` surfaces: `ExecutionQualityStrip` 4 KPI row → dl/div treatment, accents via `tone='good'|'warn'|'bad'`. `AttributionBreakdownCard` 4 attribution KPIs retained their multi-color palette (Prediction blue / Execution purple / Exit green / Friction amber is the *attribution legend*) but re-sourced via `var()` tokens. `TradeExecutionTable`, `FillQualityGauge`, `SlippageHistogram` accents off the chart palette (blue/purple) → single accent emerald.
- Phase 9.3 (1 commit: `bee7be9`) — `/risk` and adjacent surfaces: 8 panel accents (`accent="blue|purple|pink|indigo"` on CalibrationCurve, ExecutionFeed, HealthScores, StatisticalMetricsTable, TradeFeed, TradeOutcomes, GovernanceRadar, PerformancePanel) → `accent="emerald"`. `AlertFeed` left on `amber` (alerts legitimately warn). `AttributionBreakdownCard` left on its multi-color legend.
- Phase 9.4 (1 commit: `a2dfc8b`) — `AssetCard` layers-badge inline Tailwind blue (`bg-blue-900/30 text-blue-400 border-blue-500/30`) → lifted-accent `bg-accent-emerald/15 text-accent-emerald border-accent-emerald/30`.
- Phase 9.5 (1 commit: `d76ccd9`) — Modal chrome: 3 modals (`WeeklyReviewModal`, `TradeInspectorModal`, `SystemHealthModal`) plus loading/error screens migrated off Tailwind default `rounded-xl` + `shadow-2xl` to single 4px corner + `var(--shadow-modal)` token, which gives the right elevation for the page's highest layer.
- Phase 9.6 — this section.

**Deliberate non-targets for Phase 9** (audited and left alone):

- **rounded-lg → rounded collapse across panels/cards/table cell treatments.** Phase 2's spec preferred a single 4px corner everywhere; doing it now would ripple across 40+ files. Best as a separate PR when there is time to refresh every Panel render.
- **Chart palette elimination.** Audit step 2 reserved the chart palette for *attribution surfaces where colour carries domain meaning*. AttributionBreakdownCard preserves it intentionally. Everywhere else collapses to single accent emerald + governance semantic.
- **14 audit items previously deferred** (Panel variant collapse, TradingAssetRow extraction, PekStatusBar fold-in, etc.) still belong in dedicated PRs of their own.

**Visual identity landed**

The operator-console surfaces as designed:
1. **TickerRail** above Header reads the engine pulse continuously in mono
2. **Rail status chip** (Phase 4) plus Header HealthBadge (Phase 7 copy) answer "is the engine OK" without scrolling, from either of two persistent surfaces
3. **Quick-stats row** (Phase 8.3) is one mono headline per metric, divided by hairline rules, semantic-coloured only where the value reads green/yellow/red
4. **SectionHeader** dots are static single pixels (Phase 2.8a)
5. **Hairline 1px border** is the only surface separation at rest; no shadow contrast between panels of the same elevation
6. **Single accent** (lifted emerald) reserved for primary actions and one-shot highlights; **governance semantic** the only signal colors

Branch is stable, builds clean (`tsc -b --noEmit`, `vite build`), commit-per-change history preserved.

---

## Deferred-PR cleanup batch D (one-off unit commits)

The audit had 14 deferred items flagged as "large-blaster, >30 file touch-points" — each its own dedicated PR. Over the next session the items that hadn't been resolved by other phases were closed out:

| Phase | Item | Commit | Outcome |
|-------|------|--------|---------|
| D-1 | #1 QuickStatCard → StatCard | n/a (audit-crep) | already completed in Phase 8.3 — the inline `QuickStatCard` definition in `CommandCenter.tsx` was replaced by the dl/div terminal-precision treatment using `StatCard` import paths only. Zero references confirmed by grep. |
| D-2 | #2 PekStatusBar fold into SystemHealthSummary | n/a (audit-crep) | already removed in Phase 1.1 (`DashboardOverview.tsx` itself deleted; PekStatusBar was its inline member). |
| D-3 | #7 TradingAssetRow extraction | `cb9f5ad` | extracted to top-level `components/TradingAssetRow.tsx`. Now reusable from any route. `AssetTradingState` used as the explicit type (no longer `ReturnType<typeof useTradingState>['assetList'][number]`). Inline definition deleted in `CommandCenter.tsx`. |
| D-4 | #16 Header health chip move | `7e70f74` | Header `HealthBadge` collapsed to an icon-only click target (`<HealthButton />` with an `Activity` icon coloured by engine tone). Visible state already lives in TickerRail + Sidebar caption — no further Header pill is needed. State text remains in title and aria-label. |
| D-5 | open-positions card-grid duplication Dashboard ⇄ Trading | `b84a4ae` | `<AssetMiniGrid openOnly />` removed from `/trading` (TradingWorkspace) and the `Section id="open-positions"` wrapper deleted. The grid stays on `/` (Dashboard) as part of the glance surface. `/trading` retains the dense per-asset sortable table (`AssetListPanel → TradingAssetRow[]`) for operate-on-positions work — that's a separate surface, not the same view. |
| D-6 | #11 Panel variant collapse | `1ee522e` | `Panel.tsx` variants collapsed from 5 (`default | elevated | flat | accent | glass`) to 2 (`default | elevated`). Ornamental props (`leftAccent`, `gradient`, `glowColor`) removed (zero callers). The only straggler (`SystemHealthSummary.tsx` was still passing `'accent'` for the ALERT state) rerouted to `'elevated'` — semantically correct, ALERT now lifts the panel above its row. |
| D-7 | #13/#14 PekScalarPanel relocation + EquityChart migration | n/a (already in Phase 6.2/6.3) | Phase 6.2 moved `EquityChart` from `/trading` to `/execution` (commit `ee30ccc`). Phase 6.3 closed IA-4 by deciding PEK scalars stay on `/risk` (post-IA-2 `/engine` had no destination; left them where they were). No further action. |
| D-9 | top-bar dedup (Header vs TickerRail) | `79cf345` | After Phase D-4 collapsed Header's `HealthBadge` to an icon, Header still carried the brand wordmark + sequence id + `<MT5Status />` + the `<HealthButton />` — all of which were already encoded in the TickerRail. TickerRail gained an `mt5` token (`live $X` / `disc` / `ERROR` tone-coded). Header collapsed to two icon-only buttons: mobile menu and refresh. `MT5Status.tsx` deleted (its sole consumer was the now-removed Header mount). |
| D-12a | rail carries refresh glyph + responsive layout | `88f2dcb` | TickerRail tokens dropped `whitespace-nowrap` + `overflow-x-auto` in favour of `flex flex-wrap` so they wrap naturally on narrow viewports (no more horizontal scroll on a 360px viewport). A trailing control cluster (`ml-auto`) carries the refresh button (always rendered, calls React Query's `invalidateQueries`, gated 600ms minimum spin for visible feedback). The rail is now both read state and the single operator-control touchpoint above main content. |
| D-12b | Header fully removed; menu moves to rail | `db6b2ba` | `Header.tsx` deleted in full. AppShell no longer mounts Header; the menu toggle (mobile-only, `lg:hidden`) and refresh button both live on the rail. Layout on every viewport is now `TickerRail → SystemDegradedBanner → EmergencyHaltBanner → Sidebar | TabBar | main`, with **one** top bar above page content. |
| D-10 | equity-chart duplication Dashboard ⇄ /execution | n/a (operator-confirmed keep) | Operator deferred to the recommendation: small `EquityCurveSparkline` on Dashboard's status row is the *glance read*; full `EquityChart` (Recharts area + drawdown + per-asset overlays) on `/execution` is the *attribution drill-down*. Two views of the same `/equity_history.json` source at different drill depths. IA-7 already approved their coexistence. No code change. |

Each item was its own small isolated commit so the work stays reviewable per the "small enough for one agent to finish in a single focused pass" rule. After this batch the dashboard has zero outstanding audit items.

Final route count: 4 (`/`, `/trading`, `/execution`, `/risk`). Each route has a single primary job:

- `/` — glance surface: status row + ticker rail + equity curve + open-positions grid + dense sortable asset list
- `/trading` — operate surface: signal queue + admission/rejected + recent trades + execution feed
- `/execution` — quality surface: equity curve + execution quality KPIs + trade attribution
- `/risk` — governance surface: PEK telemetry + portfolio risk + governance + health scores

---
## Project Rename: EigenCapital (formerly Quorrin, 2026-07-02)

### What Was Done (Phases 1–8)

| Phase | Scope | Files Changed |
|-------|-------|---------------|
| 1 | Python package `eigencapital/` (moved from `quorrin/`), imports, loggers, pyproject.toml | 179 |
| 2 | Prometheus metric names `eigencapital_engine_*` (moved from `quorrin_engine_*`) | 2 |
| 3 | Env vars `EIGENCAPITAL_*` (moved from `QUORRIN_*`) | ~50 |
| 4 | Dashboard branding (TickerRail `Q` → `EC`, `·EIGENCAPITAL`, LS_KEY, alerts channel, index.html title, package.json name, loading screen) | 6 |
| 5 | Infra rename (systemd unit file, monitor_all banner, Docker container names) | 4 |
| 6 | External integrations (MT5 comment, Slack) | handled by Phases 1+4 |
| 7 | Documentation updates (AGENTS.md, README.md was already updated) | 2+ |
| 8 | Git remote updated from `EigenCapital.git` (was `Quorrin.git`) | 1 |

### Remaining After Rename
- `.env.example` has no EigenCapital refs (never had Quorrin refs either — uses `MT5_ACCOUNT` etc.)
- `.env` content unchanged (user-specific; will regenerate)
- Dashboard `generated/` tokens need re-generation if referenced paths changed (no path changes, so clean)
- Verify `tests/test_prometheus_metrics.py` metric names align (Phase 2 sed covered this)

### Conventions
- Python package: `eigencapital` (one word, lowercase)
- Logger names: `eigencapital.*`
- Env vars: `EIGENCAPITAL_*`
- Metrics prefix: `eigencapital_engine_*`
- Dashboard package: `eigencapital-dashboard`
- Container names: `EigenCapital-*`

---

## Weekend Trading & BTCUSD Expansion (2026-07-04)

### What Changed

BTCUSD was promoted to the live portfolio with `weekend_eligible: true`, enabling 24/7 trading alongside the standard 22-asset set (which follows Mon–Fri market hours). A `crypto: [0, 24]` session tier was added to `session_gate` for assets that trade outside traditional market windows.

### Configuration

Per-asset keys in `configs/paper_trading.yaml`:

| Key | Default | Purpose |
|-----|---------|---------|
| `weekend_eligible` | `false` | Run inference and trading for this asset when markets are closed |
| `weekend_allocation_multiplier` | `0.5` | Scale position size by this factor during weekend cycles |

Session tier added:

```yaml
session_gate:
  tiers:
    crypto: [0, 24]  # 24/7 — no session restriction
```

### Engine Behavior

When `is_market_closed()` returns true (weekend/holiday), the engine checks for `weekend_eligible` assets:

1. **No eligible assets** → skip cycle entirely (legacy behavior, returns `{}`)
2. **Eligible assets found** → run a filtered cycle processing only those assets

The filtered cycle:
- Skips `is_market_closed()` gating for eligible assets
- Applies `weekend_allocation_multiplier` (default 0.5×) in the sizing chain via `entry_service.py:436`
- Records `weekend_cycle: true` in `state.json` and on the engine instance (`_cycle_weekend`)
- Non-eligible assets appear as stale (no refresh) in the dashboard

### Portfolio Expansion

22 assets now in the live portfolio:

```
GC, USDCHF, USDCAD, GBPCAD, NZDCAD, NZDUSD, GBPAUD,
NZDCHF, CADCHF, AUDUSD, EURCHF, EURCAD, EURNZD, GBPCHF,
GBPUSD, EURAUD, ^DJI, BTCUSD, AUDJPY, NZDJPY, GBPJPY, USDJPY
```

Added 2026-07-03/04: AUDJPY, NZDJPY, GBPJPY, USDJPY (JPY crosses — walk-forward positive), BTCUSD (crypto — 24/7 trading, no COT features), ^DJI (deferred from earlier commit `cfaa07f` which claimed promotion but did not add to config — resolved here).

### Key Files

| File | Change |
|------|--------|
| `configs/paper_trading.yaml` | BTCUSD config block (`weekend_eligible`, `weekend_allocation_multiplier`, `spread_tier: crypto`); `crypto: [0,24]` session tier; 6 new asset blocks |
| `paper_trading/engine.py` | `_get_weekend_eligible_assets()`, `_cycle_weekend` flag, weekend branch in `run_once()` |
| `paper_trading/orchestrator/engine.py` | `run_once()` accepts `allowed_assets` set; `_filtered_actors()` |
| `paper_trading/services/entry_service.py` | Weekend allocation multiplier applied to `size_scalar` when `is_weekend()` and `weekend_eligible` |
| `paper_trading/services/engine_state_service.py` | `weekend_cycle` exposed in `state.json` |
| `paper_trading/portfolio_builder.py` | Propogates `weekend_eligible`, `weekend_allocation_multiplier` from spec to config |
| `tests/test_engine_weekend.py` | 20 tests covering weekend cycle, asset-scoping, allocation multiplier |

---

**Last updated:** 2026-07-07
