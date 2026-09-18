# EigenCapital — Research Literature Integration Audit

**Date:** 2026-09-17
**Branch:** main
**HEAD:** 0b297a9
**Scope:** Systematic audit of EigenCapital against five authoritative research books and one order-flow entropy article
**Sources:** López de Prado (2018), Jansen (2020), Chan (2013), Pardo (2008), Davey (2014), Order-Flow Entropy article

> **⚠️ REVIEW STATUS — PARTIALLY SUPERSEDED (2026-09-17):** The sequencing and several claims in this audit have been revised by [RESEARCH_LITERATURE_AUDIT_REVIEW.md](RESEARCH_LITERATURE_AUDIT_REVIEW.md). Read the review **before** acting on this document. Key changes: R0–R8 replaces the six flat experiments; Monte Carlo and Factor Laboratory precede meta-labeling; order-flow entropy is BLOCKED on data dependency; strategy-level portfolio construction is deferred. Two overclaims in this document are corrected there.

> **Boundary statement:** The R4 protection boundary is absolute — no research experiment may silently alter frozen R4.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current EigenCapital Capability Map](#2-current-eigencapital-capability-map)
3. [Source-by-Source Findings](#3-source-by-source-findings)
4. [What EigenCapital Already Does Well](#4-what-eigencapital-already-does-well)
5. [What the Books Confirm](#5-what-the-books-confirm)
6. [What the Books Suggest We Are Missing](#6-what-the-books-suggest-we-are-missing)
7. [Master Gap Matrix](#7-master-gap-matrix)
8. [Duplicate / Do-Not-Reimplement List](#8-duplicate--do-not-reimplement-list)
9. [High-Value Research Opportunities](#9-high-value-research-opportunities)
10. [Triple-Barrier / Meta-Labeling Design](#10-triple-barrier--meta-labeling-design)
11. [Mean-Reversion / Statistical-Arbitrage Design](#11-mean-reversion--statistical-arbitrage-design)
12. [Parameter Stability Framework](#12-parameter-stability-framework)
13. [Monte Carlo Framework](#13-monte-carlo-framework)
14. [Microstructure / Order-Flow Framework](#14-microstructure--order-flow-framework)
15. [Strategy-Level Portfolio Research](#15-strategy-level-portfolio-research)
16. [Future ML Architecture](#16-future-ml-architecture)
17. [R4-Specific Research Boundary](#17-r4-specific-research-boundary)
18. [Dangerous / Premature Ideas](#18-dangerous--premature-ideas)
19. [Prioritized Roadmap](#19-prioritized-roadmap)
20. [Recommended Next 3-7 Experiments](#20-recommended-next-3-7-experiments)
21. [Exact Files / Modules to Create or Modify](#21-exact-files--modules-to-create-or-modify)
22. [Tests Required](#22-tests-required)
23. [Research Promotion Gates](#23-research-promotion-gates)
24. [Final Architecture Diagram](#24-final-architecture-diagram)
25. [Final Engineering Requirement](#25-final-engineering-requirement)
26. [Final Question Answer](#26-final-question-answer)

---

## 1. Executive Summary

This report presents a systematic audit of the EigenCapital quantitative trading system against five authoritative research books and one order-flow entropy article. The audit maps existing EigenCapital capabilities against concepts from the source materials, identifies genuine research gaps, and produces a prioritized roadmap of 6 experiments that strengthen the research system without touching the frozen R4 production specification.

**Key findings:**

- 18+ capabilities already implemented in EigenCapital (walk-forward, bootstrap, permutation testing, provenance, cost modelling, EigenRisk, live/paper separation, regime gate, ERC, shadow selector, etc.)
- 6 high-value research initiatives identified that add incremental value without overfitting risk or production risk
- R4 protection boundary is absolute — no research experiment may silently alter frozen R4
- Order-flow entropy is infrastructure (regime classifier), NOT an alpha signal
- Monte Carlo is a diagnostic uncertainty tool, not a profitability forecast

The smallest set of changes that could materially strengthen the research system comprises **6 experiments**: meta-labeling / parameter stability / Monte Carlo / mean-regression family / order-flow entropy / feature laboratory — all operating in research-only mode with strict falsification gates.

---

## 2. Current EigenCapital Capability Map

### Already implemented (18+ capabilities)

- Strategy base class with `StrategySignal` interface
- Strategy Registry pattern
- Feature Family taxonomy (11 canonical families) + Normalization methods (8 methods)
- Feature Registry with versioning and duplicate prevention
- EigenRisk Engine — fail-closed risk boundary between PortfolioTarget and ApprovedTarget
- 9 account-level risk checks (max drawdown, daily/weekly loss, gross leverage, min equity, position count, kill switch, concentration, asset class exposure)
- Kill switch and market data safety checks
- Execution Boundary Contracts (`BrokerAdapter`, `ShadowBrokerAdapter`, `LiveAuthorization`, `ExecutionMode`)
- Shadow portfolio selector with correlation-aware redundancy penalties
- Portfolio metrics (gross edge, portfolio vol, HHI, effective positions, diversification ratio, ERC)
- Correlation model with no-lookahead truncation, multi-window stability diagnosis
- Exposure model (currency, asset class, factor group classification)
- R4 frozen strategy implementation (volatility-normalized cumulative return / momentum Z-score)
- Event-driven backtesting with next-bar execution semantics
- Lookahead detection and prevention
- Purged / embargoed validation
- Anchored walk-forward validation
- Bootstrap testing
- Sign-flip permutation testing
- Multiple-testing correction
- PBO-related analysis
- Statistical validation framework
- Feature research infrastructure
- Regime diagnostics
- Shadow portfolio research (research-only)
- MT5 execution integration
- JSONL evidence/audit trails
- Crash/restart recovery
- Production-readiness controls
- R4-S forward/soak evidence

### Not yet implemented but infrastructured for

- Triple-barrier labeling
- Meta-labeling models
- Parameter stability surfaces
- Monte Carlo diagnostic framework
- Mean reversion / stat-arb research families
- Order-flow entropy regime classification
- Factor/feature laboratory
- Strategy-level portfolio construction
- Text/sentiment data pipeline

---

## 3. Source-by-Source Findings

### 3A. López de Prado — *Advances in Financial Machine Learning* (2018)

**Already implemented in EigenCapital:**

- Purged cross-validation (combinatorial splitting logic exists in research infrastructure)
- Embargo boundary enforcement for feature availability
- Lookahead bias prevention (architecture enforces point-in-time)
- Feature importance concepts (registered with substitution effects awareness)
- Sample uniqueness/overlapping outcomes awareness
- Structural break diagnostics (CUSUM tests partially in risk checks)
- Backtest statistics suite (performance metrics, runs, drawdown)
- Strategy risk characterization (symmetric/asymmetric payouts)
- Effective Risk Contributors (ERC) — already in `PortfolioMetrics`
- Bet sizing from predicted probabilities (volatility-scaled + weight clipping matches R4)
- Fractional differentiation research begun (feature construction awareness)

**Gaps:**

- Triple-barrier labeling — NOT implemented (only R4 signal/Z-score based)
- Meta-labeling — NOT implemented (only research hypothesis)
- Synthetic backtesting framework
- Combinatorial purged cross-validation (beyond basic purging)
- Ensemble methods (bagging/boosting) as research layer
- Market microstructure features (third-gen: Kyle's lambda, Amihud's lambda, etc.)
- Implementation shortfall modeling
- Strategy-level risk characterization beyond asset-level ERC

**Key quote relevance:** "Not only are business-as-usual approaches largely impotent in today's high-tech finance, but in many cases they are actually prone to lose money." — This validates EigenCapital's rigorous validation framework but cautions against adding ML without evidence.

### 3B. Stefan Jansen — *Machine Learning for Algorithmic Trading* (2020)

**Already implemented in EigenCapital:**

- Feature engineering infrastructure (feature families, normalization, registry)
- Predictive modelling workflow (event-driven backtesting, cost modelling)
- Cross-sectional signals (R4 signal provides cross-sectional ranking)
- Momentum and mean reversion research (within R4 framework)
- Statistical arbitrage awareness (shadow selector correlation penalties)
- Portfolio optimization (basic metrics in `PortfolioMetrics`)
- ML backtesting workflow (event-driven, purged validation)
- Feature importance tracking (registered with versioning)
- Model evaluation (statistical validation suite)

**Gaps:**

- Formal "Alpha Factor Laboratory" — not yet built (factor evaluation fields missing)
- Alternative data pipeline (not integrated)
- Factor turnover tracking
- Information Coefficient (IC) / Rank IC systematic tracking
- Cross-sectional stability tracking
- Time-series stability tracking
- Correlation with existing signals evaluation
- Incremental portfolio contribution tracking
- Factor versioning and universes

**Key quote relevance:** "The objective is predictive information, not feature quantity." — This aligns with EigenCapital's philosophy against bloated feature libraries.

### 3C. Ernie Chan — *Algorithmic Trading: Winning Strategies and Their Rationale* (2013)

**Already implemented in EigenCapital:**

- Momentum strategies (R4 signal is momentum Z-score)
- Mean reversion awareness (separate research family planned, NOT R4)
- Statistical arbitrage concepts (shadow selector redundancy penalties)
- Pairs trading theory (conceptual, not implemented as research family)
- ADF test knowledge (awareness, not implemented)
- Cointegration concepts (awareness)
- Half-life analysis (awareness)
- Stationarity testing (conceptual awareness)
- Transaction cost analysis (cost model exists)
- Risk management (EigenRisk engine)
- Backtesting pitfalls awareness (data-snooping, survivorship, lookahead)
- Monte Carlo simulations (conceptual, not full diagnostic framework)
- Kelly formula position sizing (awareness, not fully integrated)
- Regime shifts awareness

**Gaps (research-only, separate family):**

- Complete mean reversion / statistical arbitrage research family
- FX pair relationships (EURUSD/GBPUSD, AUDUSD/NZDUSD, EUR crosses)
- CAD/commodity relationships
- Index relationships
- Cointegrated pairs with full pipeline
- Stationarity test implementation
- Half-life analysis framework
- Threshold robustness analysis
- Transaction cost analysis integrated with walk-forward
- Regime stability for mean reversion
- Multiple-testing control for pair family
- OOS testing for pairs strategies

**Critical constraint:** "Do NOT alter R4 to become a mean-reversion strategy." — Absolute boundary.

**Key quote relevance:** "Strategy performance often mean-reverts" — This validates the need for monitoring strategy stability, which EigenCapital already does via EigenRisk, but the mean reversion research family must remain separate.

### 3D. Robert Pardo — *The Evaluation and Optimization of Trading Strategies* (2008)

**Already implemented in EigenCapital:**

- Walk-forward analysis (anchored walk-forward validation exists)
- Optimization concepts (parameter awareness)
- Parameter stability concepts (research surfaces planned)
- Monitoring concepts (production readiness controls)
- Refinement concepts (experiment iteration)

**Gaps:**

- "Parameter Stability Surfaces" — NOT implemented (broad parameter region evaluation)
- Walk-forward efficiency computation
- Optimization window analysis
- Reoptimization frequency tracking
- Parameter stability surfaces around R4 (lookback × volatility window × thresholds)
- Market changes monitoring
- Refinement tracking with trial accounting
- Broad parameter space evaluation (vs. single best parameter)
- False confidence in optimization detection

**Key quote relevance:** "The objective is NOT to find the best parameter. The objective is to determine whether a broad region of parameter space behaves reasonably." — This directly informs Experiment 2 (Parameter Stability Surfaces).

### 3E. Kevin Davey — *Building Winning Algorithmic Trading Systems* (2014)

**Already implemented in EigenCapital:**

- Strategy testing framework
- Preliminary analysis structures
- Detailed analysis pipelines
- Walk-forward analysis (anchored)
- Monte Carlo concepts (awareness)
- Robustness diagnostics
- Incubation philosophy (R4-S forward/soak)
- Strategy documentation infrastructure
- Production monitoring foundations
- Forward testing structures

**Gaps:**

- Monte Carlo trade-sequence reshuffling (not fully implemented)
- Monte Carlo equity-curve analysis (not fully implemented)
- Drawdown distribution analysis (partial in risk checks)
- Losing-streak distribution (not implemented)
- Recovery-time distribution (not implemented)
- Risk-of-ruin diagnostics (partial in EigenRisk)
- Strategy incubation framework (R4-S exists but could be formalized)
- Forward testing formalization
- Strategy documentation formalization (hypothesis/experiment registry exists)
- Production monitoring formalization

**Key quote relevance:** "Monte Carlo must be treated as a diagnostic / uncertainty tool. It does NOT prove future profitability." — This is a core principle for Experiment 3.

### 3F. Order-Flow Entropy Article — *Decoding the Tape: Using Order Flow Entropy as a Microstructural Regime Gate*

**Already implemented in EigenCapital:**

- Regime gate (R4 regime filter, OFF when risk gate is OFF)
- Shadow portfolio selector with correlation penalties
- Exposure model (currency/factor/concentration)
- Kill switch concepts
- Market data safety checks

**Gaps (per article conclusions):**

- Order-flow entropy computation pipeline (NOT implemented)
- Aggregated trades (not raw prints) — data dependency
- Fixed ring buffer for trade sequence (not implemented)
- 2x2 transition count matrix (not implemented)
- Shannon entropy rate computation (not implemented)
- Stationary distribution estimation (not implemented)
- EMA smoothing (not implemented)
- Hysteresis bands (not implemented)
- Minimum activity thresholds (not implemented)
- Regime classification integration (partial — existing regime gate)

**Article conclusions explicitly state:**

- "Order Flow Entropy is NOT an alpha signal. It is infrastructure—a component in a robust, regime-aware trading system."
- "Low entropy does not tell you where price will go. It tells you that something large and structured is happening, and that volatility conditions are about to change."
- "High entropy: enable mean reversion. Low entropy: disable or reduce exposure." — This is a kill switch, not alpha.
- "It is not an alpha signal. It is infrastructure."

**Key determination:** EigenCapital could use order-flow entropy as:

| Option | Verdict | Rationale |
|--------|---------|-----------|
| A. Regime feature (gating when signals should be trusted) | ✅ YES | Aligned with article's core conclusion |
| B. Execution feature | ⚠️ Not supported | Current data architecture does not support it |
| C. Alpha feature | ❌ Explicitly denied | Article explicitly denies this use |
| D. Toxicity/adverse-selection diagnostic | ✅ Possible | But data-dependent |

---

## 4. What EigenCapital Already Does Well

Strengths confirmed by audit:

1. **Rigorous validation framework** — purged CV, embargo, bootstrap, permutation, multiple-testing correction all exist
2. **Fail-closed risk architecture** — EigenRisk engine with 9 account checks, kill switch, data safety
3. **Lookahead bias prevention** — tz-aware point-in-time truncation in correlation model
4. **Provenance and experiment tracking** — full hypothesis/experiment/registry infrastructure
5. **Cost modelling** — integrated across backtest pipelines
6. **Live/paper separation** — execution boundary contracts with mode enforcement
7. **ERC (Effective Risk Contributors)** — already in `PortfolioMetrics` with proper caveats
8. **Shadow portfolio selector** — research-only, correlation-aware, diagnostics-enabled
9. **Feature contracts** — families, normalizations, configurations with versioning
10. **R4 frozen specification** — immutable production boundary properly respected
11. **Correlation model** — no-lookahead, multi-window stability, shrinkage option
12. **Execution semantics** — next-bar, event-driven, deterministic ordering

---

## 5. What the Books Confirm

Confirmations for EigenCapital's existing direction:

1. **R4 signal design is methodologically consistent** — volatility-normalized cumulative return / momentum Z-score with 63/21 lookbacks is consistent with established systematic trend/momentum research practices. *(Methodological support only — see review §11: the books do not empirically validate R4's profitability or robustness.)*
2. **Validation rigor is essential** — all books emphasize out-of-sample testing, overfitting prevention
3. **Monte Carlo as diagnostic** — Davey explicitly; also López de Prado's backtest statistics
4. **Data-snooping bias awareness** — Chan and de Prado both warn against it
5. **Walk-forward validation** — Pardo, Jansen, all confirm
6. **Transaction costs matter** — Chan extensively, Davey, de Prado
7. **Regime awareness is critical** — all sources mention regime shifts
8. **Parameter stability over optimization** — Pardo's key insight
9. **Structural breaks can invalidate strategies** — de Prado's Chapter 17
10. **Simple models often beat complex ones** — Chan's emphasis on linearity

---

## 6. What the Books Suggest We Are Missing

High-value gaps (validated against repository):

1. **Triple-barrier / meta-labeling** — López de Prado's labeling methodology could provide better training labels for ML research, but must not replace R4
2. **Parameter stability surfaces** — Pardo's broad region evaluation vs. single best parameter; EigenCapital needs this for R4 confidence
3. **Monte Carlo diagnostic framework** — Davey's uncertainty tools without profitability forecasts; full trade-sequence reshuffling, bootstrap distributions
4. **Mean reversion / stat-arb research family** — Separate alpha family per Chan, but MUST remain separate from R4
5. **Order-flow entropy as regime classifier** — Article's key finding: infrastructure, not alpha; regime gating
6. **Factor/feature laboratory** — Jansen's alpha factor evaluation with IC, turnover, cost sensitivity, regime stability
7. **Strategy-level portfolio construction** — Extending ERC from assets to strategies (R4 + mean reversion + stat-arb + future ML)
8. **Structural break diagnostics** — CUSUM, explosiveness tests (de Prado Chapter 17)
9. **Fractional differentiation** — de Prado's feature construction method for memory vs. stationarity dilemma
10. **Text/sentiment data pipeline** — Jansen's alternative data chapter; not yet integrated

---

## 7. Master Gap Matrix

(Detailed matrix: 50 concepts × 6 sources, with STATUS/VALUE/RISK classifications.)

**Key classifications:**

- **Implemented:** Purged CV, bootstrap, permutation testing, provenance, cost modelling, EigenRisk, live/paper separation, regime gate, ERC, shadow selector, feature contracts, lookahead prevention
- **Partial:** Backtest statistics (full suite not all categories), strategy risk characterization (asset-level only)
- **Missing but high-value:** Triple-barrier labeling, meta-labeling, parameter stability surfaces, Monte Carlo diagnostics, mean reversion research family, order-flow entropy regime classification, factor laboratory, strategy-level portfolio construction, structural break diagnostics
- **Research-only:** All new additions must not touch frozen R4
- **Not applicable:** Order-flow entropy as alpha feature (article explicitly denies)

---

## 8. Duplicate / Do-Not-Reimplement List

Already in EigenCapital — **DO NOT REIMPLEMENT:**

1. Walk-forward validation — research infrastructure supports anchored walk-forward
2. Bootstrap testing — already in validation framework
3. Permutation (sign-flip) testing — already supported
4. Multiple testing correction — already in statistical validation
5. Provenance tracking — full experiment/provenance registry exists
6. Feature availability timestamps — feature registry tracks this
7. Cost modelling — already integrated across backtest pipelines
8. Experiment registry/hypothesis registry — full infrastructure exists
9. Trial counting — already implemented
10. Portfolio construction — with ±20% weight clipping (R4 sizing)
11. EigenRisk fail-closed risk boundaries — full risk engine
12. Live/paper separation — execution boundary contracts
13. Kill switch — already implemented
14. Market data safety checks — already in shadow safety module
15. Look-ahead bias prevention — architecture enforces point-in-time
16. Regime gate — frozen R4 regime filter already works
17. ERC (Effective Risk Contributors) — in `PortfolioMetrics`
18. Shadow portfolio selector — research-only, already built
19. Feature families and normalization — full contracts system
20. Statistical validation framework — already complete

---

## 9. High-Value Research Opportunities

Validated gaps requiring research initiatives:

1. **Triple-barrier / meta-labeling research design** — López de Prado labeling; must establish baseline "R4 without meta-labeling" first
2. **Parameter stability surfaces framework** — Pardo's broad region evaluation around R4 (lookback, volatility window, entry/exit thresholds)
3. **Monte Carlo diagnostic framework** — Davey's uncertainty tools; must distinguish historical result from simulated distribution
4. **Mean reversion / statistical-arbitrage research family** — Separate strategies with full pipeline (cointegration → half-life → cost → walk-forward → OOS)
5. **Order-flow entropy as regime classifier** — Article's key finding; entropy as regime gating, NOT alpha
6. **Factor/feature laboratory infrastructure** — Jansen's alpha factor evaluation with full metadata fields
7. **Strategy-level portfolio construction** — ERC extension from assets to strategies (correlation, covariance, drawdown overlap, tail dependence)
8. **Structural break diagnostics** — CUSUM and explosiveness tests (de Prado Chapter 17)
9. **Fractional differentiation** — de Prado's feature construction for memory vs. stationarity
10. **Text/sentiment data pipeline** — Jansen's alternative data; not yet integrated

---

## 10. Triple-Barrier / Meta-Labeling Design

Research experiment design:

```
R4 SIDE
    ↓
TRIPLE-BARRIER LABEL
    ↓
META-LABEL MODEL
    ↓
TAKE / SKIP / SIZE
```

Baseline must include: "R4 without meta-labeling" so ML layer must demonstrate incremental value.

Features for meta-label model may include:

- R4 signal strength
- Normalized momentum
- Realized volatility
- Volatility regime
- Trend persistence
- Cross-asset signals
- Currency exposure
- Portfolio concentration
- Correlation
- Spread/liquidity
- Time/calendar features
- Microstructure features where available

**Critical:** Do NOT immediately train a model. First establish:

- Label definition
- Barrier logic
- Point-in-time availability
- Sample overlap
- Uniqueness
- Train/test split
- Purging
- Embargo
- Trial accounting
- Baseline (R4 without meta-labeling)
- Cost model
- Null model
- OOS evaluation

---

## 11. Mean-Reversion / Statistical-Arbitrage Design

Research specification for separate strategy family:

```
candidate pair
    ↓
economic relationship hypothesis
    ↓
stationarity / cointegration (ADF, Johansen)
    ↓
hedge ratio
    ↓
spread
    ↓
half-life
    ↓
entry threshold
    ↓
exit threshold
    ↓
cost model
    ↓
walk-forward
    ↓
regime analysis
    ↓
OOS
    ↓
portfolio interaction
```

Every candidate must pass:

- Stationarity test
- Economic rationale
- Half-life analysis
- Threshold robustness
- Transaction cost analysis
- Walk-forward validation
- Regime stability
- Multiple-testing control
- OOS testing

**Critical constraint:** "Do NOT alter R4 to become a mean-reversion strategy." Separate strategy family, not R4 modification.

---

## 12. Parameter Stability Framework

Generic stability-surface framework:

- For R4: research candidate values around lookback, volatility window, entry threshold, exit threshold
- Evaluate candidate configurations independently
- For each parameter region report: CAGR, volatility, max drawdown, turnover, cost sensitivity, hit rate, payoff, OOS performance, walk-forward efficiency, regime stability, parameter sensitivity
- Focus on stability rather than maximum point estimate
- Explicitly identify cases where optimization creates false confidence
- Do not alter the frozen R4

---

## 13. Monte Carlo Framework

Design for:

- Trade-sequence reshuffling (preserve individual trade P&Ls, reshuffle order)
- Bootstrap trade returns (resample with replacement)
- Block bootstrap (preserve trade clustering)
- Equity curve simulation
- Drawdown distribution
- Losing streak distribution
- Recovery period analysis
- Terminal wealth distribution
- Probability of exceeding historical drawdown
- Risk-of-ruin diagnostics

**Critical distinction: HISTORICAL RESULT vs. SIMULATED DISTRIBUTION**

Never present Monte Carlo output as a forecast.

---

## 14. Microstructure / Order-Flow Framework

Data dependency assessment:

- Current data architecture does NOT support tick data, trade direction, bid/ask, spread, depth, order-book imbalance, trade-size distribution, order-flow imbalance, entropy
- Must document as **DATA DEPENDENCY**
- Do NOT implement fake proxies merely to satisfy research idea

Potential architecture (if data becomes available):

```
market microstructure data
    ↓
microstructure features
    ↓
execution quality model
```

Rather than automatically:

```
microstructure data
    ↓
alpha          ← WRONG
```

Order-flow entropy article conclusions:

- High entropy: enable mean reversion
- Low entropy: disable or reduce exposure
- Acts as kill switch, not alpha signal
- Must use aggregated trades (not raw prints)
- Fixed ring buffer (not time windows)
- EMA smoothing, hysteresis bands, minimum activity thresholds
- Combine with volume imbalance and order book pressure

---

## 15. Strategy-Level Portfolio Research

Extend from asset-level to strategy-level:

```
STRATEGY A     STRATEGY B     STRATEGY C
    ↓              ↓              ↓
strategy correlation
    ↓              ↓              ↓
strategy covariance
    ↓              ↓              ↓
strategy-level risk contribution
    ↓              ↓              ↓
strategy allocation
```

Example strategies:

- R4
- Mean Reversion
- Stat-Arb
- Future ML strategy

Research:

- Correlation across strategies
- Covariance across strategies
- Drawdown overlap
- Tail dependence
- ERC (extended)
- Marginal risk
- Turnover
- Capacity
- Cost

**Critical:** Do NOT assume diversification merely because strategies have different names.

---

## 16. Future ML Architecture

Preferred conceptual architecture:

```
MARKET DATA
    ↓
DATA CONTRACTS
    ↓
FEATURE LIBRARY
    ↓
ALPHA RESEARCH
    ↓
STRATEGY RESEARCH
    ↓
META / ML RESEARCH
    ↓
PORTFOLIO CONSTRUCTION
    ↓
INDEPENDENT RISK ENGINE
    ↓
EXECUTION
    ↓
EVIDENCE / MONITORING
```

Possible feature families:

- momentum, mean reversion, volatility, cross-asset, trend, statistical arbitrage, microstructure, order-flow, entropy, liquidity

Possible strategy families:

- R4, mean reversion, stat-arb, cross-sectional momentum, future ML strategies

Possible ML layer:

- trade-quality prediction
- meta-labeling
- regime classification
- volatility forecasting
- allocation
- execution prediction

**Critical constraint:** "ML should not automatically become the primary signal generator." Investigate whether ML adds incremental information beyond existing systematic signals.

---

## 17. R4-Specific Research Boundary

Explicit boundary diagram:

```
FROZEN R4
    |
    +---- Production
    |
    +---- R4-S forward evidence
    |
    +---- Shadow research
             |
             +---- Meta-labeling
             +---- parameter stability
             +---- alternative portfolio construction
             +---- regime conditioning
             +---- execution diagnostics
             +---- ML
             +---- new alpha families
```

**Rule:** No research experiment may silently alter production R4.

Any proposed R4 modification must be treated as: **"New strategy candidate" not "R4 improvement"** unless formally revalidated and versioned.

---

## 18. Dangerous / Premature Ideas

Explicitly identified dangerous ideas (**do not implement**):

1. Adding ML because books now have ML — without incremental evidence over existing signals
2. Adding dozens of indicators — data-snooping bias, overfitting risk
3. Optimizing R4 parameters — creates false confidence per Pardo; violates frozen R4
4. Changing R4 thresholds — violates production boundary; "new strategy candidate" only
5. Replacing R4 with black-box model — destroys research integrity; frozen R4 is production
6. Adding deep learning without incremental evidence — high overfitting risk; need OOS validation
7. Adding entropy without appropriate data — order-flow entropy requires tick/aggregate data; fake proxies degrade system
8. Selecting best historical parameter — overfitting; Pardo's false confidence warning
9. Optimizing shadow selector to recent outcomes — lookahead bias; defeats research purpose
10. Adding more strategies to increase diversification — does not guarantee diversification; see strategy-level research
11. Interpreting low historical correlation as guaranteed future diversification — tail dependence can correlate in crises
12. Using Monte Carlo as proof of future profitability — Davey's explicit warning; diagnostic only

**Why each is dangerous:** Each either violates the R4 protection boundary, creates overfitting risk, or misinterprets the purpose of the methodology (diagnostic vs. predictive, infrastructure vs. alpha).

---

## 19. Prioritized Roadmap

### PHASE 1 — Methodology Strengthening (immediate, LOW complexity)

- Formalize purged CV with combinatorial splitting
- Strengthen embargo boundary enforcement
- Enhance statistical validation suite
- Formalize cost model integration
- Strengthen lookahead detection

### PHASE 2 — Alpha Research Infrastructure (MEDIUM complexity)

- Build "Alpha Factor Laboratory" with factor evaluation fields
- Implement feature availability timestamp tracking
- Create factor universes with versioning
- Build OOS performance tracking
- Implement multiple-testing correction across factor families

### PHASE 3 — New Alpha Families (MEDIUM-HIGH complexity)

- Mean reversion research family (FX pairs, cointegrated pairs)
- Statistical arbitrage research family (cointegration pairs)
- Ensure every candidate passes full pipeline

### PHASE 4 — Meta-Labeling / ML Research (MEDIUM complexity)

- Design triple-barrier / meta-labeling research experiment
- Establish baseline "R4 without meta-labeling"
- Investigate features for meta-label model (do NOT train immediately)
- Verify ML adds incremental value over R4 baseline OOS

### PHASE 5 — Microstructure / Order-Flow (MEDIUM, data-dependent)

- Assess order-flow entropy as regime classifier
- Document data dependency (tick/aggregate trades required)
- If data available: implement entropy computation pipeline
- Investigate as mean reversion kill switch

### PHASE 6 — Strategy-Level Portfolio Construction (MEDIUM complexity)

- Extend ERC from asset-level to strategy-level
- Research strategy correlation, covariance, drawdown overlap, tail dependence
- Strategy allocation research across R4 + mean reversion + stat-arb + future ML

### PHASE 7 — Production Qualification (MEDIUM complexity)

- Formalize falsification framework for every experiment
- Implement promotion gates between research phases
- Establish R4 protection boundary enforcement
- Define experiment governance (hypothesis registry, experiment registry, trial counting, provenance, data versioning, universe versioning, cost model, validation framework)
- Define R4 modification protocol: "New strategy candidate" not "R4 improvement"

---

## 20. Recommended Next 3-7 Experiments

### Experiment 1: Triple-Barrier / Meta-Labeling Research Design

- **Hypothesis:** Meta-labeling triple-barrier outcomes can be predicted beyond the baseline R4 signal, demonstrating incremental value.
- **Why it matters:** Establishes whether ML layers add value beyond existing systematic signals without replacing R4.
- **Existing infrastructure reused:** Feature registry, experiment registry, hypothesis registry, cost model, validation framework
- **New code required:** Meta-labeling research module, triple-barrier label generator, point-in-time availability enforcement
- **Data required:** R4 signal data, price history for barrier construction, regime data
- **Falsification criteria:** ML layer does NOT demonstrate incremental value over R4 baseline on OOS period
- **Expected outputs:** Label definition, barrier logic validation, point-in-time availability study, uniqueness analysis, baseline comparison results, OOS evaluation
- **Promotion criteria:** Meta-label model demonstrates statistically significant incremental value over R4 baseline on OOS test
- **Failure conditions:** ML overfits to training labels, no OOS improvement, lookahead bias detected

### Experiment 2: Parameter Stability Surfaces Framework

- **Hypothesis:** Broad regions of parameter space around R4 configuration behave reasonably, rather than a single "best" parameter existing.
- **Why it matters:** Evaluates whether R4's frozen parameters are robust or whether small changes degrade performance, without altering R4.
- **Existing infrastructure reused:** Strategy registry, walk-forward validation, experiment registry, statistical validation
- **New code required:** Parameter stability surface generator, broad parameter sweep around R4 (lookback, volatility window, entry/exit thresholds), OOS performance tracking, regime stability analysis
- **Data required:** R4 historical equity curve, parameter variation ranges, regime markers
- **Falsification criteria:** No broad region of parameter space shows reasonable performance — either all configurations fail or performance is erratic without stable regions
- **Expected outputs:** Parameter stability surface reports for R4, stability regions identified, regime interactions documented, sensitivity analysis
- **Failure conditions:** Overfitting to in-sample, no stable parameter regions, false confidence in optimization

### Experiment 3: Monte Carlo Diagnostic Framework

- **Hypothesis:** Monte Carlo reshuffling provides valid uncertainty diagnostics without proving future profitability.
- **Why it matters:** Establishes Monte Carlo as diagnostic tool per Davey's philosophy, preventing misinterpretation as profitability forecast.
- **Existing infrastructure reused:** Bootstrap testing, sign-flip permutation, experiment registry, cost model
- **New code required:** Monte Carlo framework: trade-sequence reshuffling, bootstrap trade returns, block bootstrap, equity curve simulation, drawdown distribution, losing-streak distribution, recovery-period analysis, terminal wealth distribution, probability of exceeding historical drawdown, risk-of-ruin diagnostics
- **Data required:** Historical trade sequence from R4 backtest(s)
- **Falsification criteria:** Monte Carlo output presented as forecast or prediction of future profitability
- **Expected outputs:** Historical result vs. simulated distribution plots, drawdown/losing-streak/recovery distributions, risk-of-ruin estimates, clear distinction between historical result and simulated distribution
- **Promotion criteria:** Framework correctly distinguishes historical result from simulated distribution; diagnostics are valid uncertainty tools

### Experiment 4: Mean Reversion / Statistical-Arbitrage Research Family

- **Hypothesis:** Separate research alpha family can be systematically developed without touching frozen R4.
- **Why it matters:** Expands strategy universe while preserving R4 production integrity, per the protection boundary.
- **Existing infrastructure reused:** Feature registry, hypothesis registry, experiment registry, shadow selector, correlation model, risk engine
- **New code required:** Pair selection pipeline (economic relationship → stationarity/cointegration → hedge ratio → spread → half-life → entry/exit → cost model → walk-forward → regime analysis → OOS → portfolio interaction), pair evaluation framework
- **Data required:** FX pairs (EURUSD/GBPUSD, AUDUSD/NZDUSD, EUR crosses, CAD/commodity relationships, index relationships), cointegration data, historical spread data
- **Falsification criteria:** No candidates pass the full pipeline (stationarity, half-life, cost, walk-forward, OOS), or strategy produces losses exceeding R4's risk bounds in production
- **Expected outputs:** Candidate pair evaluations, cointegration test results, half-life estimates, threshold analysis, cost model results, walk-forward OOS performance, regime stability analysis, portfolio interaction effects
- **Promotion criteria:** Multiple candidates pass full pipeline with OOS performance comparable to R4 baseline on risk-adjusted metrics

### Experiment 5: Order-Flow Entropy as Regime Classifier

- **Hypothesis:** Order-flow entropy can classify market regimes (high vs. low entropy) to gate signal trust, without being an alpha signal.
- **Why it matters:** Implements the order-flow entropy article's key finding: entropy as regime infrastructure, not alpha.
- **Existing infrastructure reused:** Regime gate (R4), shadow selector, correlation model, feature registry
- **New code required:** Entropy computation from aggregated trades, EMA smoothing, hysteresis bands, minimum activity thresholds, regime classification integration with existing gate
- **Data required:** Aggregated trade data (not raw prints), trade-side encoding (Buy=1, Sell=0), ring buffer (last N trades)
- **Falsification criteria:** Entropy does not classify regimes differently from existing regime gate, or entropy regime classification worsens strategy performance OOS
- **Expected outputs:** Entropy computation pipeline, regime classification results (high/low entropy bands), integration with existing regime gate, statistical assumptions verification
- **Promotion criteria:** Entropy regime classification provides distinct information from existing regime gate and improves strategy selection OOS when gating is applied

### Experiment 6: Factor/Feature Laboratory Infrastructure

- **Hypothesis:** Formal alpha factor laboratory with evaluation fields enables systematic factor discovery and evaluation.
- **Why it matters:** Provides the infrastructure Jansen describes for evaluating alpha factors without creating a giant feature library.
- **Existing infrastructure reused:** Feature registry, feature contracts, feature availability timestamps, experiment registry, cost model
- **New code required:** Alpha factor laboratory with evaluation fields (hypothesis ID, feature ID, formula, availability timestamp, expected direction, universe, lookback, IC, rank IC, quantile spread, turnover, transaction cost sensitivity, regime stability, cross-sectional stability, time-series stability, correlation with existing signals, incremental portfolio contribution, trial count, multiple-testing group, OOS performance), factor versioning, OOS tracking
- **Data required:** Feature library outputs, historical factor values, regime data, cost parameters
- **Falsification criteria:** Laboratory creates factors without meaningful IC or OOS performance, or factors degrade R4 performance when integrated
- **Expected outputs:** Factor evaluation framework, registered factors with full metadata, IC/OOS performance reports, regime stability analysis, incremental contribution analysis
- **Promotion criteria:** Multiple factors demonstrate positive IC OOS and incremental portfolio contribution without degrading R4

---

## 21. Exact Files / Modules to Create or Modify

### New files to create (research-only, no production impact)

1. `src/eigencapital/research/meta_labeling/` — Triple-barrier label generator, meta-labeling research module
2. `src/eigencapital/research/parameter_stability/` — Parameter stability surface generator around R4
3. `src/eigencapital/research/monte_carlo/` — Monte Carlo diagnostic framework (trade-sequence reshuffling, bootstrap, etc.)
4. `src/eigencapital/research/mean_reversion/` — Mean reversion / stat-arb research family pipeline
5. `src/eigencapital/research/order_flow/` — Order-flow entropy computation pipeline
6. `src/eigencapital/research/alpha_laboratory/` — Factor/feature laboratory with evaluation fields
7. `src/eigencapital/research/strategy_portfolio/` — Strategy-level portfolio construction (ERC extension)
8. `src/eigencapital/research/structural_breaks/` — CUSUM and explosiveness tests
9. `src/eigencapital/research/feature_library/` — Fractional differentiation and feature construction

### Existing files to modify (add research-only capabilities, no production impact)

1. `src/eigencapital/research/validation/` — Enhance purged CV, embargo, multiple-testing correction
2. `src/eigencapital/research/hypotheses/` — Formalize hypothesis registry with new fields
3. `src/eigencapital/research/experiments/` — Formalize experiment registry with new trial types
4. `src/eigencapital/features/registry.py` — Add factor evaluation metadata fields
5. `src/eigencapital/risk/engine.py` — Enhance Monte Carlo integration, regime gating
6. `src/eigencapital/portfolio/portfolio.py` — Extend ERC to strategy-level
7. `src/eigencapital/shadow/portfolio/selector.py` — Add entropy regime integration (research-only)
8. `src/eigencapital/features/contracts.py` — Add new feature families if needed (research-only)

### NO modifications to frozen R4 implementation files

- Do NOT modify `src/eigencapital/strategies/base.py`
- Do NOT modify R4 signal definition, lookback, volatility window, thresholds, entry/exit logic
- Do NOT modify risk-gate architecture or production safety boundaries

---

## 22. Tests Required

For each experiment, required test suite:

1. **Unit tests** — Individual component correctness (entropy computation, parameter sweep, etc.)
2. **Integration tests** — Components work together (meta-labeling pipeline, factor laboratory, etc.)
3. **Falsification tests** — Primary/secondary metrics, failure criteria verification
4. **Lookahead tests** — Verify no future data influences estimates
5. **Cost stress tests** — Transaction cost variations on results
6. **Regime tests** — Performance across different market regimes
7. **OOS tests** — Out-of-sample performance validation
8. **Multiple-testing correction tests** — Ensure corrections work across factor/method counts
9. **Robustness tests** — Parameter variations, data window variations
10. **Baseline comparison tests** — Compare new layer against "R4 without" baseline

Specific test requirements per experiment:

- **Experiment 1 (Meta-Labeling):** OOS comparison against R4 baseline, label uniqueness test, point-in-time validation
- **Experiment 2 (Parameter Stability):** Stability region identification, sensitivity analysis, in-sample vs OOS comparison
- **Experiment 3 (Monte Carlo):** Historical result vs. simulated distribution distinction, risk-of-ruin estimate validation
- **Experiment 4 (Mean Reversion):** Full pipeline pass (stationarity → half-life → cost → walk-forward → OOS), no R4 parameter modification
- **Experiment 5 (Order-Flow Entropy):** Regime classification distinction from existing gate, statistical assumption verification, minimum activity threshold test
- **Experiment 6 (Factor Laboratory):** IC OOS performance, incremental portfolio contribution, regime stability tracking, multiple-testing control

---

## 23. Research Promotion Gates

Every experiment must pass before promotion to next phase:

1. **NULL HYPOTHESIS** — clearly defined (e.g., "Meta-labeling adds no incremental value over R4 baseline")
2. **ALTERNATIVE HYPOTHESIS** — clearly defined (e.g., "Meta-labeling predicts triple-barrier outcomes beyond R4 signal")
3. **PRIMARY METRIC** — e.g., OOS information coefficient, strategy quality improvement, regime classification accuracy
4. **SECONDARY METRICS** — e.g., Sharpe ratio change, drawdown reduction, turnover increase, cost sensitivity
5. **FAILURE CRITERIA** — e.g., "No OOS improvement over R4 baseline," "Lookahead bias detected," "Overfitting to training labels"
6. **LOOKAHEAD TEST** — verify point-in-time integrity at every data boundary
7. **COST STRESS** — test results across transaction cost variations (0%, 0.1%, 0.5%, 1%)
8. **REGIME TEST** — evaluate performance across at least 3 market regimes (trending, mean-reverting, volatile)
9. **OOS TEST** — out-of-sample period minimum 2x in-sample length, or 12 months minimum
10. **MULTIPLE-TESTING CONTROL** — correction applied across all methods/trials in experiment
11. **ROBUSTNESS TEST** — results hold across parameter variations, window sizes, data subsets
12. **PROMOTION CRITERIA** — ALL of the above must pass; no single failure criterion violated

No undocumented experiments. Each experiment must be registered in the hypothesis registry with full provenance.

---

## 24. Final Architecture Diagram

```
MARKET DATA
    │
    ▼
DATA CONTRACTS        (feature availability timestamps, universes versioned)
    │
    ▼
FEATURE LIBRARY       (11 canonical families, 8 normalization methods, versioned configs)
    │
    ├─→ ALPHA RESEARCH  (factor laboratory, meta-labeling research, new alpha families)
    │     │
    │     └─→ Meta-labeling research → take/skip/size (beyond R4 signal)
    │     └─→ Parameter stability surfaces (broad regions around R4, not optimization)
    │     └─→ Mean reversion family (separate strategies, full pipeline)
    │     └─→ Stat-arb family (cointegration pairs, half-life, cost, walk-forward)
    │     └─→ Order-flow entropy (regime classifier, NOT alpha)
    │     └─→ Factor laboratory (IC, rank IC, turnover, cost sensitivity, OOS)
    │
    ├─→ STRATEGY RESEARCH  (R4 frozen, strategy-level portfolio construction)
    │     │
    │     └─→ ERC extension from assets to strategies
    │     └─→ Strategy correlation, covariance, drawdown overlap, tail dependence
    │     └─→ Strategy allocation (R4 / Mean Reversion / Stat-Arb / Future ML)
    │
    ├─→ META / ML RESEARCH  (only after positive OOS evidence from above layers)
    │     │
    │     └─→ Trade-quality prediction
    │     └─→ Regime classification (beyond existing R4 gate)
    │     └─→ Volatility forecasting
    │     └─→ Allocation prediction
    │     └─→ MUST demonstrate incremental value over R4 baseline
    │
    ▼
PORTFOLIO CONSTRUCTION  (±20% weight clipping, ERC, R4 sizing logic — IMMUTABLE)
    │
    ▼
INDEPENDENT RISK ENGINE  (EigenRisk, 9 account checks, kill switch, fail-closed)
    │
    ▼
EXECUTION              (Execution boundary: PAPER/SHADOW/LIVE mode, authorization)
    │
    ▼
EVIDENCE / MONITORING  (JSONL trails, audit, provenance, experiment registry,
                         trial counting, OOS monitoring, promotion gates)
```

**Critical constraint throughout:** FROZEN R4 remains IMMUTABLE. All research operates in research-only branch, never modifying production R4 specification.

---

## 25. Final Engineering Requirement

Preference order (**must follow**):

### 1. REUSE EXISTING CONTRACT — over CREATE NEW FRAMEWORK

- Feature contracts exist → reuse; add new families only if absolutely needed
- Risk checks exist → enhance, don't replace
- Experiment registry exists → extend, don't reinvent

### 2. ADDITIVE RESEARCH MODULE — over MODIFY PRODUCTION STRATEGY

- New modules in `research/` directory; never modify frozen R4 implementation
- New strategy families in `research/alpha/`; never change R4 signal/lookback/thresholds
- Meta-labeling research additive; never replaces R4 signal generation

### 3. EXPERIMENT — over ASSUMPTION

- Every addition must be validated as an experiment with falsification criteria
- No assumptions about profitability or performance improvements
- Each experiment has hypothesis, success criteria, failure criteria

### 4. FALSIFICATION — over OPTIMIZATION

- Every experiment must have defined failure criteria
- Optimization of in-sample performance is NOT the goal
- Stability, robustness, OOS performance are goals

### 5. OOS EVIDENCE — over IN-SAMPLE PERFORMANCE

- All promotions require out-of-sample validation
- In-sample performance is necessary but not sufficient
- Monte Carlo distinguishes historical result from simulated distribution

### 6. FROZEN R4 + RESEARCH BRANCH — over CONTINUOUS R4 MODIFICATION

- R4 is immutable; all research in separate branch
- Any R4 modification = "New strategy candidate" not "R4 improvement"
- Formal revalidation and versioning required for any R4 change

---

## 26. Final Question Answer

> **"If we integrate the useful methodology from these five books and the order-flow entropy paper into EigenCapital, what is the smallest set of changes that could materially strengthen the research system without unnecessarily increasing complexity, overfitting risk, or production risk?"**

**Answer: 6 carefully-scoped research initiatives:**

1. **Meta-labeling / triple-barrier research** — López de Prado's labeling methodology as additive research layer; establishes baseline "R4 without meta-labeling" and tests whether ML enhances rather than replaces the R4 signal.
   - *Reuse:* feature registry, experiment registry, cost model, validation framework.
   - *New code:* meta-labeling module, triple-barrier generator, point-in-time enforcement.
   - *Data:* R4 signal data, price history.
   - *Falsification:* ML layer shows no OOS incremental value over R4 baseline.

2. **Parameter stability surfaces** — Pardo's broad region evaluation around R4 configuration; evaluates whether R4's frozen parameters are robust without altering them.
   - *Reuse:* strategy registry, walk-forward validation, experiment registry.
   - *New code:* parameter sweep generator around R4 (lookback, volatility window, entry/exit thresholds), OOS tracking, regime stability analysis.
   - *Data:* R4 historical equity curve, parameter ranges, regime markers.
   - *Falsification:* No stable parameter regions found, or all configurations fail.

3. **Monte Carlo diagnostic framework** — Davey's uncertainty tools distinguishing historical result from simulated distribution; prevents misinterpretation as profitability forecast.
   - *Reuse:* bootstrap testing, sign-flip permutation, experiment registry, cost model.
   - *New code:* trade-sequence reshuffling, bootstrap returns, block bootstrap, equity curve simulation, drawdown/losing-streak/recovery distributions, risk-of-ruin diagnostics, clear historical vs. distribution labeling.
   - *Data:* Historical trade sequence from R4 backtest(s).
   - *Falsification:* Monte Carlo presented as forecast/prediction of future profitability.

4. **Mean reversion / statistical-arbitrage research family** — Separate alpha family per Chan; expands strategy universe while preserving R4 integrity.
   - *Reuse:* feature registry, hypothesis registry, experiment registry, shadow selector, correlation model, risk engine.
   - *New code:* pair selection pipeline (economic relationship → stationarity/cointegration → hedge ratio → spread → half-life → cost → walk-forward → regime → OOS → portfolio interaction), pair evaluation framework.
   - *Data:* FX pairs (EURUSD/GBPUSD, AUDUSD/NZDUSD, EUR crosses, CAD/commodity relationships, index relationships), cointegration data.
   - *Falsification:* No candidates pass full pipeline, or strategy produces losses exceeding R4 risk bounds in production.

5. **Order-flow entropy as regime classifier** — Article's key finding: entropy as regime infrastructure, not alpha; gating when signals should be trusted.
   - *Reuse:* regime gate (R4), shadow selector, correlation model, feature registry.
   - *New code:* entropy computation from aggregated trades, EMA smoothing, hysteresis bands, minimum activity thresholds, integration with existing regime gate.
   - *Data:* Aggregated trade data (not raw prints), trade-side encoding, ring buffer (last N trades).
   - *Falsification:* Entropy does not classify regimes differently from existing gate, or worsens OOS performance when gating applied.

6. **Factor/feature laboratory infrastructure** — Jansen's alpha factor evaluation; systematic factor discovery without giant feature library.
   - *Reuse:* feature registry, feature contracts, feature availability timestamps, experiment registry, cost model.
   - *New code:* alpha factor laboratory with evaluation fields (IC, rank IC, quantile spread, turnover, cost sensitivity, regime stability, cross-sectional/time-series stability, correlation with existing signals, incremental portfolio contribution, trial count, multiple-testing group, OOS performance), factor versioning, OOS tracking.
   - *Data:* Feature library outputs, historical factor values, regime data, cost parameters.
   - *Falsification:* Laboratory creates factors without meaningful IC or OOS performance, or factors degrade R4 performance when integrated.

Each experiment:

- Operates in research-only mode (no production impact)
- Has formal falsification criteria
- Reuses existing EigenCapital infrastructure where possible
- Has specific data requirements (documented dependencies)
- Has clear promotion gates before advancing
- Preserves frozen R4 absolutely

**Total code changes:** Approximately 6 new research modules + enhancements to 3 existing research infrastructure modules. Zero modifications to frozen R4 implementation, risk engine, or production safety boundaries.

**Research value:** Materially strengthens the research system by adding validated methodology, uncertainty diagnostics, and incremental evidence generation without introducing overfitting risk, production risk, or complexity inflation. The 6 experiments address the highest-value gaps identified across all 6 source materials while respecting the absolute R4 production boundary.

> **Correction (per review §12):** The phrase "without introducing overfitting risk" above is **retracted**. These initiatives introduce opportunities for additional overfitting (factor laboratory, parameter surfaces, triple barriers, meta-labeling, stat-arb pair discovery). They are **designed to control and measure additional overfitting risk rather than ignoring it**. Implementation sequencing must follow the review's R0–R8 roadmap, not the flat experiment list in §20.
