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

**Key finding:** Five driver clusters identified: yield_equity (XLF), momentum_crypto (BTC), carry_fx (NZDJPY), usd_macro (EURUSD — blocked), real_asset (GC=F — blocked). Assets within the same cluster share feature engineering patterns. NZDJPY improved from 0/7 to 5/7 positive windows after switching from generic to cluster-specific features.

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

Three assets from independent driver clusters (yield_equity, momentum_crypto, carry_fx) produce max pairwise PnL correlation 0.055. Portfolio Sharpe estimate: 0.69 minimum vs 0.40 for XLF alone. Simultaneous failure: 9/251 days (3.6%).

**Why it works:** True diversification requires independent risk factors, not just different tickers. XLF, BTC, and NZDJPY respond to different macro drivers and fail under different conditions. The portfolio benefit exists because the assets are economically independent, not just statistically uncorrelated.

### Expanding Window With Recency Weighting

Expanding window outperforms rolling on every metric. Recency weighting (linear 1.0 → 0.5) prevents old data from dominating while keeping regime diversity.

**Why it works:** Macro-conditioned models need to experience multiple rate cycles. A 5-year expanding window includes hiking, cutting, and neutral regimes. The recency weighting ensures the model adapts to the current regime shape without discarding relevant historical context.

---

## 4. What Remains Blocked and What Data Would Unblock It

### EURUSD — Blocked Pending COT Data

**Blocking issue:** The residual analysis identified CFTC positioning data as the missing axis. Our feature set captures macro environment (rates, yields, USD) but not positioning (who holds what).

**Data needed:** Weekly CFTC Commitment of Traders reports for EURUSD (commercial, non-commercial, and managed money positions). Requires: a) automated parsing of CFTC weekly CSV files, b) daily interpolation of weekly position data, c) feature engineering (net positioning z-scores, positioning extreme indicators, 1W and 4W change in speculative positioning), d) walk-forward validation with the new features.

**Estimated effort:** 1-2 weeks for data pipeline + 2-3 weeks for validation.

### GC=F (Gold Futures) — Blocked Pending Inflation Data and Regime Diversity

**Blocking issue:** Two problems. First, gold's primary drivers are real yields and inflation expectations — we have the real yield data but not inflation breakevens (TIPS breakeven: 10y Treasury yield minus 10y TIPS yield). Second, gold's training data lacks regime diversity — the 2016-2024 period is mostly a gold bull market, producing the same L/S ratio problem as SPY (11.00:1).

**Data needed:** a) St. Louis FRED series T10YIE (10-year breakeven inflation rate), b) longer history for gold (ideally 2000-present to include the 2013-2015 bear market), c) macro features specific to real assets (real rate regime, inflation regime, central bank gold reserve data).

**Estimated effort:** 1 week for data + 2 weeks for validation. The regime diversity problem may require accepting a longer walk-forward with more frequent retraining.

### Interactive Brokers / Alpaca Integration — In Progress

**Blocking issue:** The execution/ module contains only stubs. The paper trading engine runs on yfinance data and simulates fills at close. Moving to real execution requires broker-specific order management, fill simulation, position reconciliation, and error handling.

**Data needed:** Broker API credentials, order management system (order lifecycle: PENDING → SUBMITTED → FILLED/PARTIALLY_FILLED → CANCELLED/REJECTED), portfolio sync (reconcile local state with broker positions), error handling (connection loss, rejected orders, market hours).

**Estimated effort:** See execution roadmap in PAPER_TRADING_RUNBOOK.md.

### Risk-Parity Portfolio Allocation — In Progress

**Blocking issue:** The portfolio/ module has HRP and risk parity implementations marked "in progress." Current allocation uses fixed weights (40/35/25).

**Data needed:** Validated correlation and volatility models for the three-asset portfolio. The current 0.055 max correlation may be period-specific and needs ongoing monitoring. Requires: a) rolling correlation estimator, b) volatility forecasting, c) rebalancing schedule, d) backtest against fixed-weight baseline.

**Estimated effort:** 2-3 weeks for implementation + 2 weeks for validation.
