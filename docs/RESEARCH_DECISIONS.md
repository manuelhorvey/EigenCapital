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

### Near-Zero Correlation Portfolio

Six assets from independent driver clusters (momentum_crypto, real_asset, eur_cross, carry_fx, oil_carry, usd_macro) produce max pairwise signal |r| < 0.40, with most pairs < 0.20. True diversification across 5 distinct macro risk factors.

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

**Resolution:** BTC was removed from the core portfolio and placed in a `HighVolSatellite` bucket at 5% AUM cap. Marginal contribution analysis confirmed that BTC's 60-80% annualised vol and 77% 2022 drawdown corrupted portfolio-level Sharpe and drawdown metrics even at 20% allocation. The satellite isolation preserves upside convexity while preventing tail events from corrupting core metrics. See [ADR-018](../docs/adr/ADR-018-btc-satellite.md).

### Risk-Parity Portfolio Allocation — In Progress

**Blocking issue:** The portfolio/ module has HRP and risk parity implementations marked "in progress." Current allocation uses fixed weights across 6 assets (GC=F 20%, EURAUD 22%, NZDJPY 15%, CADJPY 13%, USDCAD 10%). BTC is excluded.



**Data needed:** Validated correlation and volatility models for the six-asset portfolio. The current max |r| < 0.40 may be period-specific and needs ongoing monitoring. Requires: a) rolling correlation estimator, b) volatility forecasting, c) rebalancing schedule, d) backtest against fixed-weight baseline.

**Estimated effort:** 2-3 weeks for implementation + 2 weeks for validation.
