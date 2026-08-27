# ML4Trading Gap Analysis — Phased Research Roadmap

Based on: *Machine Learning for Algorithmic Trading* (Stefan Jansen, 3rd Edition, 2020)

## Core Principle

> **Don't build an ML trading system because ML4Trading says ML is powerful.**
> **Build an ML layer because EigenCapital's evidence proves there is a specific prediction problem that ML can plausibly solve.**

The book is a **research roadmap**, not a checklist of missing production features.

---

## Where EigenCapital Is Now

| Phase | Purpose | Status |
|-------|---------|--------|
| **Phase 0** | Research foundation | ✅ Done |
| **Phase 1** | Production hardening | ✅ Done |
| **Phase 2** | Prove R4 survives reality | 🟢 **RUNNING** |
| **Phase 3** | Improve alpha/portfolio using evidence | ⏳ After Phase 2 |
| **Phase 4** | Scale proven edges | ⏳ After Phase 3 |

**We are squarely in Phase 2.** The best thing EigenCapital can do is sit there and trade frozen R4 under hardened infrastructure while collecting evidence. That's not "doing nothing" — that's the experiment that determines what we should build next.

---

## What EigenCapital Already Does Well

| Area | Status | Notes |
|------|--------|-------|
| Factor-based signal construction | ✅ | R4 momentum with multi-timeframe features |
| Walk-forward validation | ✅ | Embargo-aware with out-of-sample testing |
| Multiple-testing correction | ✅ | Bonferroni, BH/FDR, deflated Sharpe |
| Falsification culture | ✅ | R5 (16/16 rejected), M1-1H frozen |
| Risk enforcement | ✅ | 7-gate broker-authoritative enforcement |
| Production infrastructure | ✅ | Reconciliation, health states, event ledger |
| Backtesting framework | ✅ | Cost-aware with basic execution modeling |

---

## Phase 2 — KEEP RUNNING

**Do not touch R4.** Collect live economic evidence.

### Evidence Categories

| Category | What to Measure |
|----------|----------------|
| **Entry** | Signal strength, spread, slippage, entry efficiency, initial MAE/MFE |
| **Hold** | 1d/3d/5d/10d/20d/40d+ returns, MAE/MFE evolution, signal decay, regime changes |
| **Exit** | Rotation, sign flip, regime exit, catastrophic SL, opportunity cost after exit |
| **Portfolio** | Correlation, concentration, exposure, drawdown, daily loss, loss clustering |
| **Execution** | Latency, rejects, partial fills, spread, swap, disconnects, reconciliation |

### Exit Criteria

Phase 2 ends when we can answer:
- Does R4 make money live?
- Do entries match research?
- Does the 20-40 day thesis hold?
- Are catastrophic SLs rare?
- Is portfolio risk controlled?
- Does the system survive failures?

---

## Phase 3 — The Alpha Factory

**Trigger:** Phase 2 evidence confirms R4 has a live edge.

### 3A — Understand R4 Before Replacing R4

This is the most important phase. Before building ML, answer:

| Question | Method |
|----------|--------|
| Why does Q5 work? | Feature importance analysis on live trades |
| Why do Q1-Q4 fail? | Compare feature distributions Q5 vs Q1-Q4 |
| Which features distinguish winners? | SHAP values, permutation importance |
| Is momentum strength actually the alpha? | Ablation study |
| Is volatility conditioning responsible? | Conditional analysis by regime |
| Is cross-asset regime conditioning responsible? | Factor decomposition |
| Is the edge asymmetric LONG vs SHORT? | Direction-specific analysis |
| Which assets contribute the edge? | Per-asset attribution |
| Which regimes destroy it? | Regime-conditional performance |
| How much return comes from a small number of trades? | Return distribution analysis |

**This becomes the R4 Alpha Decomposition Study.**

### 3B — ML as Prediction Layer (Not Replacement)

ML doesn't immediately replace R4. Initially:

> **R4 generates the opportunity set. ML evaluates opportunity quality.**

```text
R4 momentum
     ↓
Candidate opportunities
     ↓
Feature engine
     ↓
ML quality model
     ↓
P(profitable)
Expected return
Expected MAE
Expected MFE
     ↓
Portfolio allocator
     ↓
Risk engine
     ↓
Execution
```

This turns:
> "R4 says BUY"

Into:
> "R4 says BUY, but historical conditional evidence says this particular BUY has only 31% probability of producing sufficient return."

**Model progression:** Rules → statistical factors → linear models → GBMs → ensembles → only then deep learning if evidence demands it.

Start with LightGBM/XGBoost (already have XGBoost experience from earlier ML work).

### 3C — Portfolio Construction (Progressive Complexity)

**Don't jump to HRP.** Test progressively:

| Step | Method | Complexity |
|------|--------|-----------|
| 1 | Current R4 weighting | Baseline |
| 2 | Equal weight | Minimal |
| 3 | Inverse volatility | Low |
| 4 | Volatility targeting | Low-Medium |
| 5 | Correlation-aware sizing | Medium |
| 6 | Risk parity | Medium-High |
| 7 | HRP | High |
| 8 | More sophisticated allocator | Very High |

**Key principle:** If inverse-volatility weighting gives 90% of the improvement of HRP with 20% of the complexity, **use inverse volatility.**

### 3D — Transaction Cost Modeling

**Higher priority than originally placed.** At $5K it's not dominant; at $50K+ it becomes critical.

```text
Signal return
   ↓
Spread
   ↓
Slippage
   ↓
Commission
   ↓
Swap/financing
   ↓
Market impact
   ↓
Implementation shortfall
   ↓
Actual alpha
```

Components:
- Cost model (spread, commission, slippage, impact)
- Execution algorithms (TWAP, VWAP, IS)
- Cost-aware sizing

### 3E — Strategy Diversification

**Only after R4 is understood.** Test new strategies for independence, not just Sharpe.

> A mediocre Sharpe strategy with negative correlation to R4 can be more valuable than another high-Sharpe momentum strategy that simply duplicates R4.

| Category | Strategies |
|----------|-----------|
| Cross-sectional | Momentum, mean reversion, relative strength, dispersion |
| Time-series | Trend following, breakout, volatility breakout, regime-conditioned |
| Relative-value | Pairs, cointegration, stat arb |
| ML | Classification, regression, ranking, meta-labeling, conditional sizing |

**A new strategy is valuable if its returns are sufficiently independent from R4.**

---

## Phase 4 — Advanced + Scaling

| Work | Notes |
|------|-------|
| Advanced portfolio optimization | HRP, Black-Litterman, robust MVO |
| Execution optimization | Market impact models, optimal execution |
| Alternative data/NLP | Sentiment, satellite, flow data |
| Strategy ensemble | Multi-strategy allocation |
| Capital scaling | $5K → $10K → $25K → $50K |

---

## What NOT to Build Yet

| Technology | Why Not |
|-----------|---------|
| Deep learning (Transformers, LSTMs, TCN, Mamba) | Tools in the workflow, not mandatory architecture |
| RL / autonomous agents | Premature without proven alpha |
| Alternative data pipelines | Not needed until strategies require it |
| Advanced execution algorithms | Not needed at $5K |

**Rule:** Rules → statistical factors → linear models → GBMs → ensembles → only then deep learning if evidence demands it.

---

## Priority Ranking

| # | Work | Phase | Status |
|---|------|-------|--------|
| 🔴 1 | Finish R4 live economic qualification | **Now** | Running |
| 🔴 2 | R4 alpha decomposition study | Phase 3 | Deferred |
| 🔴 3 | Conditional ML signal-quality model | Phase 3 | Deferred |
| 🔴 4 | Correlation/vol-aware portfolio sizing | Phase 3 | Deferred |
| 🟠 5 | Better transaction-cost/impact model | Phase 3 | Deferred |
| 🟠 6 | Alternative strategy research | Phase 3 | Deferred |
| 🟠 7 | Strategy ensemble | Phase 3/4 | Deferred |
| 🟡 8 | Advanced portfolio optimization | Phase 4 | Deferred |
| 🟡 9 | Execution optimization | Phase 4 | Deferred |
| 🟢 10 | Alternative data/NLP | Later | Deferred |
| 🟢 11 | Deep learning | Only if justified | Deferred |
| 🟢 12 | RL/autonomous research agents | Much later | Deferred |

---

## The Real Architecture (Eventually)

```text
                    RESEARCH FACTORY
                           │
          ┌────────────────┼────────────────┐
          ↓                ↓                ↓
       R4 Alpha         ML Alpha         New Alpha
          │                │                │
          └────────────────┼────────────────┘
                           ↓
                  SIGNAL / ALPHA LAYER
                           ↓
                 PORTFOLIO CONSTRUCTION
                           ↓
             correlation / vol / exposure
                           ↓
                     RISK ENGINE
                           ↓
                 TRADING AUTHORIZATION
                           ↓
                    EXECUTION ENGINE
                           ↓
                       BROKER
                           ↓
                 RECONCILIATION
                           ↓
                EVIDENCE / MONITORING
                           │
                           └──────────────┐
                                          ↓
                              RESEARCH FEEDBACK LOOP
```

---

## Estimated Effort (Post Phase 2)

| Phase | Component | Effort |
|-------|-----------|--------|
| 3A | R4 alpha decomposition | 2-4 weeks |
| 3B | ML prediction layer | 4-6 weeks |
| 3C | Portfolio optimization | 3-4 weeks |
| 3D | Transaction cost model | 2-3 weeks |
| 3E | Strategy diversification | 4-8 weeks |
| 4 | Advanced + scaling | 4-8 weeks |

**Total:** 19-33 weeks of focused research

---

## Critical Constraint

> **All of this is deferred until Phase 2 evidence confirms R4 has a live edge.**

The current priority is:
1. Let R4 run frozen
2. Collect live economic evidence
3. Prove or disprove the R4 hypothesis
4. Then understand why R4 works before trying to improve it

---

*This roadmap is derived from the ML4Trading book's structure, adapted to EigenCapital's current architecture, and prioritized by the principle: understand before you improve.*
