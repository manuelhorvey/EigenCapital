# Research Reference: Jansen, *Machine Learning for Algorithmic Trading* (2nd ed., 2020)

> **Status: RESEARCH REFERENCE — not an architectural authority.**
> This document extracts research principles, candidate hypotheses, and domain
> knowledge from Stefan Jansen's ML4T (2020). Nothing here overrides EigenCapital's
> contracts ([RESEARCH_ENGINE_CONTRACT.md](../RESEARCH_ENGINE_CONTRACT.md),
> [DATA_CONTRACT.md](../DATA_CONTRACT.md)). Where the book's practices conflict with
> our contracts, **our contracts win**.
>
> Companion repository (150+ notebooks): https://github.com/stefan-jansen/machine-learning-for-trading
> Use as a source of research ideas to be translated into EigenCapital Hypotheses →
> Experiments → validated candidates. Do **not** copy its architecture or stack.

---

## Core Principle

> **The book is a hypothesis generator, not a source of alpha.**
> Every idea extracted here enters the pipeline as an unproven candidate:
>
> ```
> Hypothesis → Data → Feature → Statistical evidence → Out-of-sample validation
> → Cost-adjusted backtest → Robustness → Portfolio contribution → Paper → Live
> ```
>
> Simplicity bias is deliberate: if a simple rule matches a complex model
> out-of-sample, EigenCapital ships the simple rule. The objective is
> survivability and robustness, not technological sophistication.

---

## Scope Mapping: Book → Roadmap

| Book material | EigenCapital phase | Disposition |
|---|---|---|
| Market/fundamental data (Ch 2–3) | **1B Data Foundation** | Extract now |
| Financial feature engineering (Ch 4) | Future Feature Engine | Extract now |
| Alpha-factor research (Ch 4, Appendix) | **1G+ Statistical Research** | Hypothesis source |
| Portfolio optimization (Ch 5, 13) | Portfolio/Risk expansion | Extract on demand |
| ML process / validation (Ch 6) | ML research layer | Principles only |
| Time-series models (Ch 9) | Strategy research | Later |
| Bayesian ML (Ch 10) | Strategy research | Later |
| Random forests / boosting (Ch 11–12) | ML strategy experiments | Only after 1G |
| Unsupervised learning (Ch 13) | Portfolio/factor research | Later |
| NLP/sentiment (Ch 14–16) | Alternative-data research | Much later |
| Deep learning (Ch 17–21) | Only if justified | Default: no |
| Reinforcement learning (Ch 22) | Probably never | Reference only |
| Conclusions (Ch 23) | System principles | Adopted below |

---

## Keep vs. Modernize

The book targets a 2020 educational stack (Zipline, backtrader, pyfolio,
Quantopian, TF2/PyTorch notebooks). Extract principles; do not reproduce the stack.

**Keep (methodology):**

- Factor taxonomy with economic rationale (momentum, value, low-vol/size, quality)
- Alpha-factor evaluation methodology: IC, quantile analysis, turnover
- Point-in-time data discipline; look-ahead/survivorship-bias awareness
- Time-series-aware cross-validation: walk-forward, purging, embargoing
- Backtest pitfall taxonomy and multiple-testing controls
- Portfolio construction thinking: baselines first, estimation-error awareness
- Model diagnostics: learning curves, bias-variance reasoning, SHAP attribution

**Modernize (EigenCapital already owns or will own these):**

- Data architecture → `data` layer + DATA_CONTRACT (immutable bars, catalogue)
- Experiment tracking/version lineage → `research.experiments`, provenance hashing
- Validation framework → Phase 1G statistical engine (to be built)
- Backtesting engine → `backtest.engine` under RESEARCH_ENGINE_CONTRACT
- Execution simulation → spread/slippage models in the contract
- Risk architecture → `risk` layer adjudicates, never research code
- Observability/reconciliation/monitoring → dedicated layers

---

## Extraction by Layer

### Data Foundation (Phase 1B)

1. **Bar regularization beyond time bars.** Aggregate ticks by time, but also by
   **volume** (order fragmentation) and **dollar value** (price-level changes).
   Bar fields: OHLCV **+ VWAP + transaction count**. Volume/dollar bars exhibit
   better statistical properties (closer to normal/IID returns) than time bars.
   → Candidate feature/bar types for the normalization layer; asset-agnostic
   formulation required (e.g., "notional bars" instead of dollar bars).
2. **Storage format guidance.** Pure numeric series: HDF5 fastest. Mixed
   numeric/text: Parquet best read/write. Parquet is the default for
   `data/normalized`; benchmark before deviating.
3. **Point-in-time discipline is a data-layer invariant**, not a research habit:
   timestamps must reflect publication availability, not period covered
   (fundamentals are quarterly; prices daily). Aligns with DATA_CONTRACT.
4. **Survivorship bias**: the instrument catalogue must track historical universe
   membership (delistings, bankruptcies, mergers), not just currently active names.

### Features Engine (future)

1. **Factor taxonomy** (each needs an economic rationale before implementation):
   - *Momentum*: 12-1 month return (skip last month), RSI(14), price acceleration
     (slope change of volatility-adjusted trend), % off 52-week high, volume-
     normalized momentum. Rationales: under-/over-reaction biases, supply-demand
     frictions, hedging-flow feedback.
   - *Value*: EBITDA/EV, FCF yield, forward earnings yield, PEG, book yield,
     dividend yield, sector-relative P/E. Rationale: mean reversion to fair value.
   - *Low-volatility/size*: realized vol, beta, idiosyncratic vol. Rationale:
     lottery-effect and leverage-constraint behavioral premiums.
   - *Quality*: gross profitability, ROIC, accruals (negative proxy for earnings
     quality), interest coverage, asset turnover. Often combined with value
     ("quality at a reasonable price").
2. **Formulaic alpha DSL** (Kakushadze 2016, "101 Formulaic Alphas"; ~80%
   were in production at WorldQuant). Operator vocabulary implementable from
   OHLCV+VWAP+ADV(d):
   - Cross-sectional: `rank` (percentile), scale, group-neutralize by sector
   - Time-series: `ts_lag`, `ts_delta`, `ts_rank`, `ts_mean`, `ts_weighted_mean`
     (linearly decaying weights), `ts_sum`, `ts_product`, `ts_stddev`,
     `ts_max/ts_min`, `ts_argmax/ts_argmin`, `ts_correlation(x, y, d)`
   - Example: Alpha#101-001 = `rank(ts_argmax(power((returns < 0) ? ts_std(returns,20) : close, 2), 5)) - 0.5`
   - These become declarative feature expressions in our features package —
     versioned, hashable, point-in-time safe.
3. **Signal denoising**: Kalman filter (state-space smoothing of noisy levels),
   wavelets (multi-scale denoising). Optional post-Phase-2 additions.

### Statistical Research (Phase 1G) — evaluation standards

These define how any candidate factor/feature must be judged. They belong in the
1G statistical validation engine, not ad hoc notebooks.

1. **Information Coefficient**: Spearman rank correlation between signal and
   forward returns per period. IC ≈ 0.05 is meaningful; report IC mean/std,
   t-stat (H0: IC=0), IC by year, IC decay across horizons (5D/10D/21D/42D).
2. **Quantile analysis**: bucket signals into quintiles; forward returns must
   separate monotonically (top vs bottom quantile spread). Check dispersion
   (violin), not just means.
3. **Factor turnover**: share of names entering a quantile per rebalance;
   rank autocorrelation > ~0.7 preferred at short horizons. High turnover can
   consume the entire edge after costs.
4. **Fundamental law of active management**: IR ≈ IC × √breadth (× transfer
   coefficient). Small edges are viable only with many independent bets.
   Breadth must count *independent* forecasts, not correlated ones.
5. **Cross-validation adapted to finance** (IID assumption fails: serial
   correlation + heteroskedasticity):
   - Walk-forward with expanding or rolling window (`TimeSeriesSplit` semantics)
   - **Purging**: remove training samples whose label window overlaps test labels
   - **Embargoing**: buffer after test periods before training resumes
   - Combinatorial CV (López de Prado) for more tested paths when warranted
   - Three-way split discipline: train/validation via CV + untouched hold-out
6. **Multiple-testing controls**: record number of trials per dataset
   (Experiment Registry field); deflated Sharpe ratio (Bailey & Prado) for
   strategy selection among many trials; minimum-backtest-length heuristic:
   2y of daily data supports ≤ ~7 strategy variants; 5y supports ~45.
7. **Backtest validity checklist** (encode as engine/test-suite items):
   - Look-ahead bias: point-in-time inputs only (contract-enforced)
   - Survivorship: historical universe membership
   - Outliers: analyze extremes; do not silently winsorize real market events
   - Sample period must include relevant regimes (crises, high/low vol)
   - Mark-to-market over time; rolling VaR/Sortino, not just endpoint stats
   - Realistic costs: commission + half-spread + slippage/market impact
   - Sequencing: signal-at-close → execute next bar (already contractual)
   - Optimal-stopping heuristic: test ~37% (1/e) of candidate pool, then adopt
     the first that beats all prior tests

### Portfolio Construction (later phases)

1. **Always ship naive baselines**: equal-weight (1/N) beat mean-variance
   out-of-sample until MV had ~3,000 months of history for 25 assets (~6,000
   months for 50). Any optimizer must beat 1/N and GMV to justify existence.
2. Mean-variance fragility ("Markowitz curse"): inverting ill-conditioned
   covariance matrices yields unstable weights. Prefer constrained/shrunk
   estimators; consider Black-Litterman (reverse-engineer expected returns from
   market-cap weights; Bayesian blend with views).
3. **HRP (hierarchical risk parity)**: distance matrix `d = sqrt((1-corr)/2)` →
   agglomerative linkage (single) → top-down bisection allocating inverse-variance
   weights within/between clusters. Avoids covariance inversion entirely.
   Note: in Jansen's own comparison, MV > EW > HRP on his sample — results are
   context-dependent; treat HRP as a robustness candidate, not a winner.
4. **Eigenportfolios**: PCA on normalized return covariance → principal
   components as portfolio weights. PC1 ≈ market (~40–55% of variance), later
   PCs behave like sector/style factors. Data-driven risk factors require no
   ex-ante factor assumptions; useful for both risk decomposition and
   uncorrelated allocation sleeves.
5. Kelly criterion for bet sizing: f* = p − (1−p)/b (binary case); maximize
   expected log growth. Fractional Kelly in practice. Bankruptcy protection is
   inherent (log(0) = −∞).

### ML Research Layer (only after 1G proves the harness)

- Complexity ladder per candidate signal family, each step must justify itself:
  ```
  simple rule → regime conditioning → linear model → tree ensemble → boosting
  ```
- Gradient boosting (LightGBM/XGBoost/CatBoost) is the book's strongest
  tabular performer; ensembling top-CV-fold predictions was standard practice.
- Interpretability gate: SHAP attribution required before any black-box model
  is considered production-eligible — predictions must be explainable against
  the stated economic rationale.
- Deep learning (CNN/RNN/autoencoders/GANs) and RL: reference-only. RL reward
  design for trading remains unsolved in practice; revisit only if a concrete,
  justified use case emerges.

---

## Candidate Hypothesis Seed List

Each item below is an *unvalidated candidate* for `research/hypotheses/`.
None carries implied alpha.

| Family | Candidates from the book |
|---|---|
| `trend/` | Time-series momentum (12-1m); price acceleration; % off 52-wk high |
| `momentum/` | Cross-sectional momentum deciles; volume-normalized momentum; analyst revision breadth |
| `mean_reversion/` | Short-term reversal (1-month); RSI(14) overbought/oversold; sector-relative value spreads |
| `breakout/` | 52-week high proximity; range-expansion (vol-adjusted) |
| `volatility/` | Low-vol anomaly (realized vol, beta); vol-of-vol; VIX-sensitivity tilt |
| `cross_sectional/` | Quality tilts (ROIC, gross profitability); accruals (negative); earnings-yield fwd |
| `statistical_arbitrage/` | Cointegration pairs (Engle-Granger, Johansen); DBSCAN-clustered pairs; Bayesian rolling-beta pairs |
| `factor/` | PCA eigenportfolios; data-driven risk factors; Fama-French replication as baseline |
| `ml/` | Boosted long-short on engineered factors (Ch 12 workflow); complexity-ladder comparisons |
| `alternative_data/` | Earnings-call sentiment; SEC-filing embeddings; news topic novelty |

---

## Ch 23 System Principles (adopted)

1. Data quality dominates model sophistication.
2. Domain expertise prioritizes hypotheses *before* testing (limits the
   multiple-testing trap).
3. ML is a toolkit; prefer human-in-the-loop and interpretable solutions.
4. Learning curves diagnose bias vs variance before adding capacity.
5. Track trial counts; deflate reported Sharpe ratios.
6. Staged paper trading precedes live capital — always.

---

## Change Log

| Date | Note |
|---|---|
| 2026-08-23 | Initial extraction from full-text read of ML4T 2nd ed. (821 pp.) |
