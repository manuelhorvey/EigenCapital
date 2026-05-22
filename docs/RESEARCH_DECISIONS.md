# QuantForge — Research Decisions

This document summarizes the 6-month investigation arc that shaped QuantForge's architecture. It is written for a quant developer joining the project who needs to understand why the system looks the way it does without repeating the experiments that produced the answers.

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

### Meta-Model Validation — AUC 0.49-0.55 (Random)

**Hypothesis:** A logistic regression secondary filter trained on live trade outcomes can distinguish winning from losing primary signals.

**Result:** Holdout validation across all 8 assets with > 200 trades: AUC 0.49 (AUDJPY) to 0.55 (EURCAD). Effectively random. Removed from all production paths in `asset_engine.py` and `survival_sim.py`. The `shared/meta_labeling.py` module kept as reference for future research.

**Why it failed:** The primary XGBoost models already produce well-calibrated probabilities. The 5 meta-model features (primary confidence, regime state, periods in state, stability penalty, close price) do not contain incremental information that the primary model has not already exploited.

**Lesson learned:** A secondary filter cannot improve on a primary model that has already learned its own failure modes. The +5–19% Sharpe lift observed during development was from random gating (the meta-model was randomly skipping losing trades), not from genuine skill.

### Near-Zero Correlation Portfolio

**Why it works:** True diversification requires independent risk factors, not just different tickers. BTC responds to liquidity conditions, GC=F to real yields and inflation, EURAUD to EUR/AUD rate differentials, NZDJPY to carry trade dynamics, CADJPY to oil and Canada-Japan spreads, USDCAD to USD momentum. The portfolio benefit exists because the assets are economically independent, not just statistically uncorrelated.

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

### Portfolio Expansion — 11 to 14 Assets (CHFJPY, EURCAD, ^DJI)

**Resolution:** 32 tickers registered and walk-forward screened. 10 passed the promotion gate. Historical 5-year sandbox governance narrowed to 4 candidates. CL=F rejected (avg Sharpe −0.33 in historical backtest — regime overfit to 2020 crash). GBPNZD held back (only 3/5 consistent windows). Three promoted:

- **CHFJPY**: avg Sharpe 0.89 (WF), 1.62 (historical), 5/5 windows, plateau SL/TP at 0.50/1.70
- **EURCAD**: avg Sharpe 0.52 (WF), 1.41 (historical), 5/5 windows, plateau SL/TP at 0.51/1.96
- **^DJI**: avg Sharpe 1.53 (historical), 4/5 windows, started underweight at 5%; marginal contribution ΔSharpe −0.11 (under observation)

**14-asset survival sim results**: Sharpe 6.02 (was 3.78), worst DD 8.3% (was 27.5%), flash crash DD 34.1% (was 35.8%), ruin 0%, 100% positive paths. Return compression −2.4% is the expected trade-off for diversification and well within bounds.

**Lesson learned**: Single-metric walk-forward gates can miss regime overfitting (CL=F case). Historical 5-year governance is necessary as a secondary filter. Plateau-center SL/TP selection is more robust than global max Sharpe.

### Risk-Parity Portfolio Allocation — In Progress

**Blocking issue:** The portfolio/ module has HRP and risk parity implementations marked "in progress." Current allocation uses fixed weights across 14 assets (see README §4).

**Data needed:** Validated correlation and volatility models for the 14-asset portfolio. The expansion to 14 assets may shift pairwise correlation structure. Requires: a) rolling correlation estimator, b) volatility forecasting, c) rebalancing schedule, d) backtest against fixed-weight baseline.

**Estimated effort:** 2-3 weeks for implementation + 2 weeks for validation.
