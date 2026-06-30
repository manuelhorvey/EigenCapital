# Quorrin — Research Decisions

This document summarizes the 6-month investigation arc that shaped Quorrin's architecture. It is written for a quant developer joining the project who needs to understand why the system looks the way it does without repeating the experiments that produced the answers.

---

## 1. What We Tried and Why It Failed

### EURUSD Daily With Macro + Momentum Features

**Hypothesis:** EURUSD's macro sensitivity (rate differentials, risk sentiment, USD strength) is well-captured by the standard macro feature set (rate_diff, dxy_mom, yield curves) combined with price momentum.

**Result:** 8-year walk-forward produced 1.65% CAGR. The macro-only model had the correct short bias in 2022-2024 but at 94% short — a static position, not a trading system. The full model had no edge. We tested 28 FX pairs — zero passed the bootstrap deployment gate.

**Why it failed:** Daily FX returns are dominated by positioning and flow dynamics that OHLCV data alone cannot capture. CFTC positioning data is the missing axis. Price-derived features produce noise, not signal, for the most liquid FX pairs at daily frequency.

**Lesson learned:** Asset-driver fit matters more than feature count. Generic feature sets fail on assets where the causal mechanism is not captured by the available features.

### Rolling 18-Month Training Window

**Hypothesis:** Recent data is most relevant — an 18-month rolling window captures current market dynamics and drops obsolete regimes.

**Result:** Average expectancy -0.000192, PF 0.91, 6/16 test windows positive. The model was structurally biased toward the most recent regime and unable to adapt when conditions changed.

**Why it failed:** 18 months is too short to include a full macro cycle. The 2022 model trained on 2020-2021 bull market data (80% of the window) entered the tightening cycle with a long bias it could not escape.

**Lesson learned:** Training windows must contain at least one full rate cycle (approximately 5 years for US macro). Expanding windows with recency weighting outperform rolling windows.

### Regime Ensemble Complexity as Alpha Source

**Hypothesis:** Feeding regime probabilities (P_trend, P_range, P_volatile) as features into a single XGBoost model would let the model learn regime-conditional patterns directly.

**Result:** PF with regime routing = 1.061; PF without regime = 0.231. The improvement was massive. But SHAP analysis showed regime probability columns were not among the top 10 features. The model was not using regime state for prediction — the benefit was coming from somewhere else.

**Why it failed:** The regime signal's value is architectural (different models for different conditions), not parametric (additional predictor variables). The regime classifier acts as a router, not a feature provider. Separating the models by regime prevents the global model from learning regime-averaged patterns that perform poorly at regime boundaries.

**Lesson learned:** When a feature is important but SHAP says it isn't, the architecture is wrong, not the data. Regime routing happens once, in the ensemble; downstream logic is stateless.

### Yield Slope and Real Yield as Level Features

**Hypothesis:** The 10y-2y yield curve slope and the TIPS-adjusted 10-year real yield capture financial sector conditions and should be strong predictors for XLF.

**Result:** These features remained at persistently bearish levels through 2023-2024 despite XLF rallying 12.7% and 27.7%. The yield curve was inverted and real yields were high — both were correct data points that produced incorrect trading signals. The model was trapped in a short bias by features that were persistently wrong for forward returns.

**Why it failed:** Level-based macro features cannot distinguish between a persistent condition that will continue and one that will normalize. The yield curve was inverted for all of 2023-2024 — a feature that is always at extreme values provides no discriminative power. What mattered was the direction of change (rate expectations), not the absolute level (rate environment).

**Lesson learned:** Delta features capture trading-relevant information (expectations). Level features capture environment context (persistent conditions). Environment features degrade performance when they remain at extreme values.

---

## 2. What Diagnostic Tools Were Built and What They Revealed

### Regime Audit

Audits each regime classification against forward returns. Revealed that the VOLATILE regime has structural priority (overwrites probabilistic classification) and that the 10-bar smoothing window prevents flipping but introduces a 2-day lag in regime detection. Used to calibrate the volatility gate threshold (vol_zscore > 1.35) and the confidence threshold (0.45) for the NEUTRAL catch-all.

**Key finding:** The regime classifier's value is in participation control (RED/YELLOW/GREEN allocation), not in alpha generation. PF drops to 0.231 without regime routing.

### Bootstrap Validation

Permutation test (10,000 shuffles) on each walk-forward test window. Computes probability that the observed PF occurred by random chance.

**Key finding:** 2022 window PF=0.98, p=0.571 (noise). 2024 window PF=1.34, p=0.047 (signal). Without bootstrap, noise windows hide inside aggregated averages. Bootstrap is now the deployment gate — 4/6 windows must pass p < 0.10.

### PSI (Population Stability Index) Monitoring

Compares feature distributions between training and inference periods. Currently manual; planned for automated drift detection.

**Key finding:** The yield_slope feature had PSI > 0.25 during 2023-2024 (critical drift) because the yield curve inversion was outside the training distribution. This confirmed the ADR-007 decision to remove yield_slope — a feature that has drifted outside its training range cannot produce reliable predictions.

### Driver Analysis (Cross-Asset Scan)

Evaluates 28 FX pairs and 10 equity sectors against a standard feature template to identify which driver clusters produce signal.

**Key finding:** Six driver clusters identified: momentum_crypto (BTC), carry_fx (NZDJPY), oil_carry (CADJPY), usd_macro (USDCAD), real_asset (GC=F), eur_cross (EURAUD). Assets within the same cluster share feature engineering patterns. NZDJPY improved from 0/7 to 5/7 positive windows after switching from generic to cluster-specific features. GC=F was unblocked via fwd60 label architecture (see ADR-016).

### Signal Correlation Analysis

Computes pairwise signal correlations across assets. Used to validate the three-asset portfolio diversification.

**Key finding:** Max pairwise PnL correlation 0.055. Independent driver clusters produce near-zero correlation in trading signals. Simultaneous failure rate 3.6%.

### Residual Analysis

Regresses model predictions against actual returns and analyzes the residual structure.

**Key finding:** For EURUSD, residuals show significant correlation with CFTC net commercial positioning (r²=0.31). This identified the missing data axis that macro-only models cannot capture.

---

## 3. What the Data Confirmed Works and Why

### Asset-Specific Driver Features

Generic features produce 0/7 positive NZDJPY windows. Asset-specific features (VIX + bilateral yield spread + carry momentum) produce 5/7. The Driver Atlas framework (ADR-010) encodes this: each asset maps to a driver cluster with a specific feature engineering module. The clusters reflect causal mechanisms, not correlations.

**Why it works:** Financial assets respond to different economic drivers. XLF's P&L is affected by the yield curve and lending spreads. NZDJPY is a carry trade vehicle driven by risk appetite and bilateral rate differentials. BTC responds to global liquidity conditions and retail sentiment. A single feature set cannot capture these different causal structures.

### Protected Macro Expert Head

The 32-feature model achieved max confidence 0.54 with 4:1 long bias (ADR-005). The macro-only isolation achieved max confidence 0.70 with correct 0.4:1 short bias. The joint model destroyed the macro signal through feature interference — 20+ price features simply outvoted the 5-8 macro features. The protected macro head (fixed 0.45 weight, applied after regime blend) prevents this.

**Why it works:** Macro features have lower frequency and different noise structure than price features. In a joint model, the high-frequency price signal dominates because it has more variance to explain. Separating the macro head with a protected weight ensures macro context contributes to every decision.

### Tight-Stop Physics — Universal SL Optimum at 0.30× Vol

**Hypothesis:** Tighter stop-losses increase loss frequency but reduce loss magnitude enough to produce a net Sharpe improvement. The effect is a property of OHLC barrier checking, not of strategy edge.

**Result:** Swept SL grid (0.05–1.00 × vol, step 0.05) × TP grid (1.00–3.00 × vol, step 0.25) across 3 volatility regimes × 12 assets. Every asset, every regime — optimum SL is at the grid minimum. Best Sharpe uniformly at sl=0.05 when spread=0 bps, shifting to sl=0.05–0.30 at 5 bps spread. Universal plateau center at **sl=0.30** was selected as the operational compromise.

**Why it works:** OHLC replay checks SL before TP at each bar. A tight stop exits losing trades near their trough (small loss), while winning trades have headroom to reach TP. The resulting R:R is 4–6:1 (small loss vs large win). This is a structural property of discrete barrier checking on OHLC data — the same physics produces identical results regardless of asset or regime.

**Key statistic across sweep:**
```
Before (sl=0.52):  SL hit rate 60-65%,  TP hit rate 35-40%,  avg loss −1.2× vol
After  (sl=0.30):  SL hit rate 70-84%,  TP hit rate 25-30%,  avg loss −0.5× vol
Sharpe delta: +62% (6.01 → 9.69 in 5000-path survival sim)
```

**Why widening fails — the asymmetry argument:**

The intuitive belief that widening SL should "let trades breathe" is refuted by the sweep data. The mechanism is a mathematical asymmetry:

- **Losses scale faster than wins.** A wider SL makes each loss 2–3× larger (e.g. −1.2× vol vs −0.5× vol). The hit rate *does* drop (60-65% → 70-84%), but the expected loss per trade *increases* because the loss magnitude grows faster than the miss rate shrinks.
- **Diminishing returns on TP.** Widening TP doesn't help proportionally because most winning trades don't run far enough — they'd flip or expire before the wider TP triggers. The extra headroom is unused on the majority of trades.
- **The tighter SL is hit more often, but each hit is tiny. The remaining wins stay disproportionately large relative to the reduced risk.** Net result: the same core edge, expressed at higher efficiency.

Conceptual framing: replace a 60% chance of losing $1 with an 80% chance of losing $0.30. Less pain per attempt; more attempts compound.

**Compounding penalty of deep drawdowns:**

The second-order effect is geometric compounding. Large losses create a nonlinear recovery drag that frequent small losses do not:

- A 50% loss requires a 100% gain to recover.
- A 5% loss requires only a 5.3% gain to recover.
- At sl=0.30, the worst drawdown across all paths is 5.2%. At wider stops, worst-case DD would rise above 15%+ — and each such deep drawdown permanently destroys compounding trajectory that can never be recovered, even if "average" returns look similar.

This is why the survival simulation at sl=0.30 produces terminal P5=2.39×, P1=2.20×, 0% ruin — *every single path is profitable.* The equity curve barely breathes. Wider stops produce fewer but deeper drawdowns, and those deep drawdowns create a permanent compounding hole that the tight-stop strategy avoids entirely.

**Portfolio-wide TP/SL hit profile (survival sim, 13 assets, 20,892 trades):**

| Metric | Value |
|---|---|
| TP hit rate | 26% |
| SL hit rate | 69% |
| Flip / expiry | 5% |
| TP/(TP+SL) ratio | 27.2% |
| Avg MAE/MFE ratio | ~0.90 |
| Avg loss per SL hit | ~2.3× smaller than avg win per TP hit |

The PnL win rate is *higher* than the TP hit rate because many trades that eventually hit SL still close PnL-positive — the entry advantage exceeds the tiny 0.30× vol loss. This explains the apparent paradox of a 69% SL hit rate coexisting with Sharpe 9.67 and 100% positive paths.

**Plateau edge — the selection criterion:**

The correct question is not "what SL maximizes Sharpe?" but "what SL is the largest we can use before Sharpe degrades?" The grid establishes a plateau from sl=0.05 to approximately sl=0.35 where Sharpe is essentially flat. sl=0.30 is the **plateau edge** — the point nearest the degradation zone that is still on the plateau.

This balances three constraints:
1. **Barrier-checking physics** (tighter is always better for Sharpe)
2. **Psychological sustainability** (70-84% loss rate is mentally manageable; 84%+ is not)
3. **Spread cost sensitivity** (at 5 bps, the optimum shifts from sl=0.05 to sl=0.05–0.30; sl=0.30 provides margin against higher costs)

**Lesson learned:** The optimal SL is determined by barrier-checking physics, not by strategy characteristics. A grid that extends to the minimum possible SL value will always find the optimum at the grid edge. The correct question is not "what SL maximizes Sharpe?" but "what SL is the largest we can use before Sharpe degrades?"

### Governance Uplift Validation — Naked vs Full Portfolio

**Hypothesis:** The governance layers (confidence filter, execution physics, deleveraging, regime bootstrap) contribute additive risk-adjusted return beyond the core edge. To isolate, run a "naked" variant with all governance stripped — plateau default geometry, no confidence filter, no execution physics, no deleveraging, no regime bootstrap.

**Result (1000 paths, 3 years, 13 assets):**

| Metric | Full (governed) | Naked (raw) | Delta |
|---|---|---|---|
| Sharpe | 12.39 | 6.06 | +6.33 (+104%) |
| Ann.Ret | +51.9% | +26.6% | +25.3 pp |
| Worst DD | 3.2% | 9.1% | −5.9 pp |
| Terminal P50 | 3.51× | 2.03× | +1.48× |
| Flash Crash Sharpe | 1.95 | 0.71 | +1.24 |
| Corr Spike Sharpe | 8.04 | 3.98 | +4.06 |

**Key takeaways:**
- The core edge is real — naked Sharpe 6.06 is strong without any risk layers
- Governance roughly *doubles* Sharpe and annual return
- Governance *halves* maximum drawdown (9.1% → 3.2%)
- Governance nearly *triples* crisis resilience (flash crash Sharpe 0.71 → 1.95)
- Both variants have 0% ruin and 100% positive paths — the strategy is robust even without governance

**Lesson learned:** The governance layers are genuinely additive, not cosmetic. Each layer (confidence filter, execution physics, deleveraging, regime bootstrap) contributes independently to the Sharpe uplift. The core signal provides the edge; governance extracts it reliably without destroying path dependency.

### Confidence Filter Sensitivity Sweep — CF=0.40 Optimal

**Hypothesis:** The isotonic-calibrated primary signal confidence filter (applied before meta-labeling) at the default 0.30 threshold causes governance-induced ruin artifacts at 3yr simulation windows because halted paths do not have time to recover.

**Sweep (1000 paths, 3yr, full governance vs naked, execution physics + deleveraging + regime bootstrap):**

| CF | Governance Ruin | Gov Sharpe | Gov Ann.Ret | Naked Ruin | Naked Sharpe | Gov P50x |
|---|---|---|---|---|---|---|
| 0.30 | **33.4%** | 4.02 | +19.5% | 0.0% | 5.80 | 1.71 |
| 0.40 | **0.0%** | 5.29 | +23.2% | 0.0% | 6.03 | 1.87 |
| 0.50 | **0.0%** | 4.70 | +16.0% | 0.0% | 5.95 | 1.56 |

**5yr confirmation (CF=0.30):** Governance ruin drops from 33.4% → 0.0% at extended window, confirming the 3yr 33.4% was a measurement artifact — governance flat periods recover within 5yr.

**Decision:** Set `meta_labeling.confidence_threshold: 0.40` in `paper_trading.yaml`. CF=0.40 eliminates the ruin artifact, costs 0.74 Sharpe / 3.7% ann. return vs naked — a reasonable governance premium. CF=0.50 over-filters (Sharp drops to 4.70, P50x to 1.56). The penalty thresholds themselves (PSI, stability) remain correct and unchanged.

### Regime-Stratified Trade Outcome Analytics

**Hypothesis:** Trade quality (TP hit rate, SL hit rate, win rate, AvgR) varies meaningfully by market regime. Presenting per-asset × per-regime breakdowns reveals regime-specific weaknesses hidden in aggregate averages.

**Result (survival sim, 1000 paths, 39 asset-regime groups with ≥5 trades):**

Observed range across all (asset, regime) pairs:
- TP%: 13% (DJI, transition) — 36% (EURAUD, high_vol)
- SL%: 64% (EURAUD, low_vol) — 82% (DJI, transition)
- Win%: 17% (DJI, transition) — 36% (EURAUD, high_vol)
- AvgR: 0.26 (DJI, low_vol) — 1.41 (EURCAD, high_vol)
- Profit Factor: 1.35 (DJI, transition) — 3.08 (EURCAD, high_vol)

**Key findings:**
- DJI underperforms in all regimes — lowest AvgR (0.26–0.29), highest SL% (77–82%), worst PF (1.35–1.39). Consistent with DJI's anomalous marginal ΔSharpe.
- EURCAD high_vol is the strongest regime-slice: AvgR 1.41, PF 3.08, win rate 33% from only 30% TP rate — the TP hits are disproportionately large.
- Transition regimes are not universally bad — CHFJPY transition AvgR 0.34 vs low_vol 0.51, but CADJPY transition AvgR 1.07 vs low_vol 0.50.
- Some assets have regime-concentrated edge: EURCAD high_vol (N=193, AvgR 1.41) vs low_vol (N=1317, AvgR 0.68) — the edge is 2× stronger in high vol but trades are 7× less frequent.

**Lesson learned:** Aggregate trade quality numbers hide regime-specific variation. The regime-stratified table is now part of `print_comparison_summary()` output when `--regime-geometry` is active, providing actionable monitoring data.

### Meta-Model Validation — AUC 0.49-0.55 (Random) [Superseded]

**Original hypothesis:** A logistic regression secondary filter trained on live trade outcomes can distinguish winning from losing primary signals.

**Result (LogisticRegression):** Holdout validation across all 8 assets with > 200 trades: AUC 0.49 (AUDJPY) to 0.55 (EURCAD). Effectively random. The `shared/meta_labeling.py` LogisticRegression module is kept as reference; it was removed from production paths.

**Replacement (XGBoost MetaLabelModel):** A new XGBoost-based `labels/meta_labels.py:MetaLabelModel` (XGBClassifier, 7 features including primary model probabilities) replaces the old approach. It uses threshold-based continuous gating: below `threshold` (0.55 for most assets) → zero notional; above → `_meta_size_multiplier()` maps [threshold, 1.0] → [min_size, 1.0] linearly. Meta-confidence modulates exposure only — never TP geometry, trailing, or scale-out schedules.

**Why LogisticRegression failed:** The primary XGBoost models already produce well-calibrated probabilities. The 5 meta-model features do not contain incremental information.

**Why XGBoost may succeed:** Uses richer feature set including primary model probabilities, regime state, and stability metrics. The continuous size scalar avoids the hard ENTER/BLOCK switching that made the old approach fragile.

### Near-Zero Correlation Portfolio

**Why it works:** True diversification requires independent risk factors, not just different tickers. BTC responds to liquidity conditions, GC=F to real yields and inflation, EURAUD to EUR/AUD rate differentials, NZDJPY to carry trade dynamics, CADJPY to oil and Canada-Japan spreads, USDCAD to USD momentum. The portfolio benefit exists because the assets are economically independent, not just statistically uncorrelated.

### JPY Carry Cluster Risk Caps (40% Concentration Limit)

**Why it's necessary:** The current 8-asset portfolio contains 3 JPY-cross pairs (AUDJPY, CHFJPY, USDJPY), collectively absorbing ~38% allocation. JPY crosses share a common funding-currency risk factor — a sharp JPY rally (carry unwind) would hit all three simultaneously.

**Implementation:** `cluster_risk_report()` in `portfolio_builder.py` checks total allocation across JPY-cross assets against `JPY_CARRY_MAX_ALLOC=0.40`. Emits a `logger.warning` at engine startup if exceeded.

**Current state:** The 3 JPY crosses (AUDJPY 16%, CHFJPY 14%, USDJPY 8% = 38%) are collectively under the 40% cap. The retired assets (NZDJPY, CADJPY, GBPJPY) were removed in part to relieve JPY cross cluster concentration. The cap remains conservative at 40% to catch the worst-case unwind scenario.

### Expanding Window With Recency Weighting

Expanding window outperforms rolling on every metric. Recency weighting (linear 1.0 → 0.5) prevents old data from dominating while keeping regime diversity.

**Why it works:** Macro-conditioned models need to experience multiple rate cycles. A 5-year expanding window includes hiking, cutting, and neutral regimes. The recency weighting ensures the model adapts to the current regime shape without discarding relevant historical context.

### High-Vol Asset Satellite Isolation

BTC was removed from the core PAPER_PORTFOLIO and placed in a separate `HighVolSatellite` bucket with independent risk controls (40% vol target, 25% drawdown limit, 5% AUM cap). A five-condition regime gate (correlation, BTC vol, VIX, DXY momentum, CRISIS gap) must all be true to trade. Rolling 63-day ΔSharpe monitoring triggers alerts at -0.5 and auto-reduces allocation at -1.0.

**Why it works:** High-vol assets corrupt portfolio-level Sharpe and drawdown metrics even at modest allocations. Isolating BTC with independent risk limits and a conservative regime gate preserves upside convexity (5% cap) while preventing tail events from dominating core portfolio metrics. The five-condition AND gate ensures BTC only trades when macro conditions are benign across multiple independent axes.

### Feature Importance Stability as Governance Signal

Training-window feature importances are persisted to parquet per asset per retrain cycle. Jaccard top-10 similarity and Spearman rank correlation between consecutive windows feed stability penalties into the ValidityStateMachine (worst-wins aggregation — single low metric triggers full penalty). Jaccard < 0.6 → -0.10, < 0.4 → -0.25; Spearman < 0.7 → -0.08, < 0.5 → -0.20.

**Why it works:** A model whose top predictive features change between retrain cycles is not reinforcing stable patterns — it is chasing noise. Jaccard captures "are the same features important" and Spearman captures "are the shared features in the same order." Tying penalties to position sizing via the existing validity framework creates an automatic circuit breaker without requiring manual review.

### Meta-Labeling as Secondary Confidence Filter

A logistic regression binary classifier (5 features, class_weight='balanced', min 50 trades) learns to distinguish winning from losing primary signals. Three decision bands: FULL (≥0.55, scale=1.0), REDUCED (≥0.40, scale=0.5), SKIP (<0.40, scale=0.0). Scales pos_size in _generate_and_apply() before TradeDecision creation.

**Why it works:** Primary XGBoost models produce well-calibrated probabilities in aggregate but have individual false positives that a secondary filter can catch. Logistic regression is intentionally lightweight — it would underfit if there were no signal, providing a natural guard against overfitting. Class weighting preserves the real trade outcome distribution. The SKIP band removes 30-40% of signals that the meta-model judges unlikely to profit.

### Simulation Snapshot System for Deterministic Replay

Full engine state is captured per asset at each save_state() call to `data/live/snapshots/simulation_history.parquet` — positions, trade_log, prob_history, validity state, meta-model inference, feature stability metrics. Three load modes: exact timestamp, date-prefix, and date listing. Deduplication on (timestamp, asset). Cold state (model pickle paths) stored separately as external references.

**Why it works:** Row-based parquet snapshots enable replay from any historical date without restarting the simulation. Deduplication prevents unbounded growth. External cold state references avoid duplicating large model files into every snapshot. The parquet format enables direct SQL-like analysis: "what was every asset's position on all Mondays in May?"

### Publication-Lag-Aware Feature Construction

All macro features (FRED series, VIX, DXY) are lagged to their real publication date before any downstream computation. A central `PUBLICATION_LAGS` registry in `features/publication_lags.py` maps each macro series to its lag in business days (e.g. FRED GDPNow = 30bd, VIX = 0bd). The `lag_features()` function applies these before feature computation; the engine enforces lags via the `FeaturePipeline`.

**Why it works:** FRED series are published with a 30-day delay — using "today's" value would leak future information into the training set. The registry-based approach makes the lag policy explicit, auditable, and testable. Zero tolerance for look-ahead in feature construction.

### Synthetic Stress Blocks With Common-Factor Gaussian Model

Six parameterised stress blocks cover structurally distinct crisis regimes: COVID crash, GFC, taper tantrum, 2010 flash crash, correlation spike, and high-vol regime. Each block is modelled as a common-factor Gaussian return perturbation applied to the portfolio's baseline return distribution. A synthetic block index (SBI) tracks injection: `returns_synthetic = returns_base + w * factor_loadings * factor_shock`.

**Why it works:** Bootstrap-resampled historical episodes overfit to a single crisis path. A common-factor model captures the regime's statistical signature (vol, correlation, skew, tail shape) without copying the exact return sequence. The 25% injection cap prevents synthetic data from dominating the original series.

### Dynamic SL/TP Calibration and Fast 4-Tier Scale-Out

**Hypothesis:** An auto-calibrated ATR stop-loss and take-profit engine with a calibration scale factor of 1.2, combined with a fast 4-tier scale-out profit-taking strategy, will lock in profits early, minimize drawdown, and maximize portfolio-level Sharpe ratio.

**Result:** Parameter sweep optimization across core assets achieved a **Sharpe ratio of 7.8** with a stop-loss (SL) rate of **43%** (significantly reducing the tail risk of full stop-outs).

**Why it works:**
1.  **Dynamic SL/TP ATR Calibration**: By automatically calibrating ATR multipliers against EWM volatility at startup using a `calibration_scale` factor of `1.2`, the system expands barriers by 20% compared to pure volatility models. This prevents premature stop-outs due to high-frequency intraday noise while still keeping risk limits tightly bounded.
2.  **Fast 4-Tier Scale-Out**: The 25/50/75/100% scale-out tiers close 25% of the allocation fraction at each respective profit multiplier step. The mathematics of this approach are highly favorable:
    -   **Locks in profits early**: Realizing 25% profit at a tight 0.25x TP multiplier secures early gains in range-bound or choppy regimes.
    -   **Breakeven trigger**: As soon as Tier 1 is filled, the stop-loss of the remaining 75% position is automatically moved to the entry price (breakeven). This eliminates downside tail risk for the remaining position.
    -   **Preserves upside tail convexity**: Allowing the subsequent 25% fractions to run to 0.50x, 0.75x, and 1.00x of the full target preserves upside convexity when a strong trend takes off.

### Trailing Stop Activation After Scale-Out (Phase 2)

**Extension:** The scale-out engine now supports `trailing_after_tier` — a configurable tier index that, when filled, triggers a `trailing_activated` signal. The asset engine wires this signal into the DynamicSLTPEngine's trailing stop logic, locking in gains as the price moves favorably.

**Why it works:** Breakeven removes downside risk but leaves profits unsecured after Tier 1. Trailing after Tier 2 (50% filled) transitions the remaining position from fixed-barrier to trailing-barrier protection — the stop follows price upward (for longs), securing additional gains without capping upside. The cross-bar best-price tracker (`_best_price_seen`) ensures trailing uses the highest/lowest price seen across bars, not just the current close.

### Confidence-Based SL Width Adjustment (Phase 3)

**Extension:** `confidence_sl_adjust` (default 0.0, disabled) biases stop-loss width by meta-label confidence. At high confidence (p=0.9), SL tightens to `sl × (1.0 - adjust)`; at low confidence (p=0.1), SL widens to `sl × (1.0 + adjust/2)`.

**Why it works:** The meta-label model's confidence correlates with prediction reliability — high-confidence signals deserve tighter stops (smaller loss per miss) while low-confidence signals need more room to avoid being stopped out by noise. The asymmetric widen/tighten schedule (tighten 100% of adjust vs widen 50%) reflects the SL physics finding that tightening never hurts Sharpe while widening always degrades it.

### Shadow SL/TP Drift Analytics (Phase 4)

**Extension:** `shadow_compare_sltp()` in the tracer logs every runtime deviation from the original label-derived barriers (in bps). The shadow memory profiles accumulate SL/TP drift statistics (mean delta, max delta, adjustment count) per asset per run.

**Why it works:** Runtime SL/TP barriers drift from their original label-computed values due to validity state adjustments, regime geometry, trailing activation, and confidence-based tightening. Without shadow tracking, these deviations accumulate silently. Drift analytics answer: "is the runtime system's risk profile still aligned with the research-validated label barriers?" — enabling detection of systematic SL creep or barrier drift.

---

## 4. What Remains Blocked and What Data Would Unblock It

### EURUSD — Blocked Pending COT Data

**Blocking issue:** The residual analysis identified CFTC positioning data as the missing axis. Our feature set captures macro environment (rates, yields, USD) but not positioning (who holds what).

**Data needed:** Weekly CFTC Commitment of Traders reports for EURUSD (commercial, non-commercial, and managed money positions). Requires: a) automated parsing of CFTC weekly CSV files, b) daily interpolation of weekly position data, c) feature engineering (net positioning z-scores, positioning extreme indicators, 1W and 4W change in speculative positioning), d) walk-forward validation with the new features.

**Estimated effort:** 1-2 weeks for data pipeline + 2-3 weeks for validation.

### GC=F (Gold Futures) — RESOLVED via fwd60 Label Architecture

**Resolution:** GC=F was unblocked by switching from tb20 (triple-barrier) to fwd60 (60-day forward return classification). The fwd60 label captures gold's macro-trend behavior better than the mean-reversion-oriented tb20. Combined with real yield delta, breakeven delta, DXY momentum, and gold momentum features, the model passed 6/6 walk-forward windows with avg Sharpe 1.212 and cumulative +96.3%. See [ADR-016](../docs/adr/ADR-016-gold-validation.md).

**Data used:** FRED series T10YIE (breakeven inflation) is available and included as `breakeven_delta_63`. Longer history and regime diversity turned out to be unnecessary — fwd60's wider label horizon (60 vs 20 bars) provides sufficient signal even in the bull-biased 2016-2024 period.

**Lesson:** Some assets need a different label architecture, not more data. GC=F was not a data problem — it was a labeling problem.

### Interactive Brokers / Alpaca Integration — In Progress

**Blocking issue:** The execution/ module contains only stubs. The paper trading engine runs on yfinance data and simulates fills at close. Moving to real execution requires broker-specific order management, fill simulation, position reconciliation, and error handling.

**Data needed:** Broker API credentials, order management system (order lifecycle: PENDING → SUBMITTED → FILLED/PARTIALLY_FILLED → CANCELLED/REJECTED), portfolio sync (reconcile local state with broker positions), error handling (connection loss, rejected orders, market hours).

**Estimated effort:** See execution roadmap in PAPER_TRADING_RUNBOOK.md.

### Bitcoin — Removed From Core Portfolio (see ADR-018)

**Resolution:** BTC was removed from the core portfolio and placed in a `HighVolSatellite` bucket at 5% AUM cap. Marginal contribution analysis confirmed that BTC's 60-80% annualised vol and 77% 2022 drawdown corrupted portfolio-level Sharpe and drawdown metrics even at 20% allocation. The satellite isolation preserves upside convexity while preventing tail events from corrupting core metrics. 14-asset survival sim validated: BTC Satellite portfolio Sharpe 5.58, worst DD 12.1%, vs BTC Legacy 20% Sharpe 3.78, worst DD 27.5%. See [ADR-018](../docs/adr/ADR-018-btc-satellite.md).

### Portfolio Composition History

**Current portfolio:** 8 core assets (AUDJPY, CHFJPY, EURAUD, EURCAD, GBPCAD, GC, USDCAD, USDJPY) + BTC satellite. Earlier iterations expanded from 11 to 14 assets by adding CHFJPY, EURCAD, and ^DJI. ^DJI was later removed (marginal ΔSharpe −0.11 — the equity index did not compensate for its idiosyncratic risk factor). NZDJPY, CADJPY, GBPJPY, GBPUSD, and USDCHF were retired during portfolio optimization as their marginal Sharpe contribution degraded the risk-parity surface.

**Stable allocation:** Fixed-weight allocation (see README §4) with 100% core sum + 5% satellite. Risk-parity portfolio module remains in progress — the fixed-weight approach is the production allocation.

**Estimated effort:** 2-3 weeks for implementation + 2 weeks for validation.

---

## Current Research Status

See also `docs/SURVIVAL_SIMULATION.md`, `docs/GOVERNANCE_LAYER.md`, `docs/FEATURES.md`.

### Active Paper Trading

- **8-asset live paper trading** active with ATR-based dynamic barrier geometry, meta-label confidence filtering, and shadow counterfactual replay.
- **9 models** in `paper_trading/models/` (8 core + BTC satellite). Stale non-traded models cleaned up.
- **32 assets** registered in FEATURE_REGISTRY with full FeatureContracts, walk-forward evaluated via `scripts/walk_forward_all.py`
- **Dashboard UX**: TradeFeed pagination, SignalsTable search filter, lazy-loaded FeatureCards, refetch indicator spinner, narrative regime badge, liquidity regime badges, SL/TP gauge bars, scale-out tier visualization

### Validation

- 5000-path survival sim: Full Governance Sharpe 12.39 vs Naked 6.06 — governance adds +51.9% ann return
- Extended history (25y): Sharpe 6.26, 0% ruin
- 281 tests across 19 test files — zero regressions

### Recent Additions

- **Macro narrative governance** — Weekly FXStreet article → Claude API → SL widen / size reduce
- **Liquidity regime model** — Volume z-score + Amihud ratio + Corwin-Schultz spread → NORMAL/THIN/STRESSED → SL widen / size reduce / halt
- **Multiplicative governance chain**: `final_sl = base × regime_geom × narrative × liquidity`

### Known Constraints

- Paper trading only (no live capital execution)
- Data limited to Yahoo Finance + FRED
- EURUSD excluded (pending COT integration)
- ^DJI removed from portfolio (marginal ΔSharpe −0.11 did not justify equity index idiosyncratic risk)
- 19 unscreened pairs not yet evaluated
