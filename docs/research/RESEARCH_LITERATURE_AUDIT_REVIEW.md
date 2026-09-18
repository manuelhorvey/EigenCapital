# EigenCapital — Research Roadmap Review & Revision

**Date:** 2026-09-17
**Branch:** main
**HEAD:** 0b297a9
**Status:** APPROVED WITH REVISIONS — this review supersedes conflicting parts of [RESEARCH_LITERATURE_INTEGRATION_AUDIT.md](RESEARCH_LITERATURE_INTEGRATION_AUDIT.md)

> **✅ LITERATURE PHASE: COMPLETE / FROZEN (2026-09-17).** The literature-audit phase is closed. No further "what else from the books should we add" expansion. The frozen R0–R8 roadmap is now a **research queue, not an architecture invitation**. The governing question for every next stage is: *does the next research stage produce evidence that survives EigenCapital's existing falsification and governance machinery?*

> **⚠️ NEXT ENGINEERING TASK: R0 — Research Infrastructure Verification.** Not another literature review. Not another architecture redesign. Not another R4 modification. R0 inspects the existing EigenCapital research machinery against the frozen R0–R8 requirements and produces a gap list classified as **PASS / PATCH / BLOCKED / DEFERRED**. If R0 finds no material defects, proceed directly to **R1 Monte Carlo**.
**Audited document:** [RESEARCH_LITERATURE_INTEGRATION_AUDIT.md](RESEARCH_LITERATURE_INTEGRATION_AUDIT.md)

---

## Verdict

The audit is **directionally correct and strong**. The overall direction survives:

> **EigenCapital does not need another giant architecture rewrite. It needs a small research layer that makes the existing system more scientifically testable.**

Pardo explicitly frames the development process around specification → testing → optimization/WFA → robustness → trading → monitoring/refinement, while Davey separately emphasizes detailed analysis, Monte Carlo and incubation. That fits EigenCapital's existing methodology unusually well.

### Keep

1. Frozen R4 boundary
2. Research-only additions
3. Factor/feature laboratory
4. Monte Carlo diagnostics
5. Parameter stability analysis
6. Separate mean-reversion/stat-arb family
7. Meta-labeling as an R4-side research layer
8. Order-flow entropy only if the required data actually exists
9. Strategy-level portfolio construction eventually

### Change

The biggest change: **do not treat the six items as six equivalent "experiments."** They are three different categories:

| Category | Work |
|----------|------|
| **Research infrastructure** | Factor Laboratory, Monte Carlo framework, parameter-surface engine |
| **New alpha/model research** | Mean reversion/stat-arb, meta-labeling |
| **Data-dependent research** | Order-flow entropy |
| **Later portfolio research** | Strategy-level allocation/ERC |

That distinction matters because infrastructure should be built **before** experiments depend on it.

---

## 1. The Biggest Issue: Phase 1 Is Partly Redundant

The audit's Phase 1 says:

> Formalize purged CV / Strengthen embargo / Enhance statistical validation / Formalize cost model / Strengthen lookahead detection

**Do not make these a new implementation phase.** The audit itself says these are substantially implemented. So instead of:

```text
PHASE 1
rebuild/strengthen validation
```

Replace with:

```text
PHASE 0 — Research Infrastructure Audit
        ↓
verify existing contracts are sufficient
        ↓
only implement demonstrable gaps
```

Otherwise we spend time polishing infrastructure that already passed hundreds/thousands of tests instead of generating new evidence.

Pardo's WFA emphasis is relevant here: the important question isn't whether you have a method called "walk-forward"; it's whether the resulting OOS process actually tests robustness and unseen data appropriately.

---

## 2. Monte Carlo Should Move Earlier

**Monte Carlo should be the first implementation.**

Why? It is largely independent of new alpha discovery. We already have:

```text
backtest → trades → equity curve → performance statistics
```

Monte Carlo can consume that existing output without changing the strategy. Davey's own structure explicitly places detailed analysis, Monte Carlo and then incubation after strategy testing. So:

```text
R4 historical trades
        ↓
Monte Carlo
        ↓
drawdown distribution
loss streaks
recovery
terminal wealth
tail scenarios
        ↓
R4-S / incubation
```

This is low architectural risk.

### One correction

The audit says:

> Falsification: Monte Carlo output presented as forecast/prediction of future profitability

That is not really a falsifiable hypothesis. Instead:

### Monte Carlo research hypothesis

> **H0:** The observed R4 path characteristics are consistent with a specified resampling/null process.

Then evaluate whether the historical path is unusual under the chosen resampling assumptions. And separately:

> Monte Carlo outputs are **conditional diagnostics under the simulation assumptions**, not forecasts of future returns.

That is a **methodological rule, not a falsification criterion**.

---

## 3. Parameter Stability Is Valuable — But Don't Call It "R4 Confidence"

This is subtle. The audit says:

> evaluates whether R4's frozen parameters are robust

Reasonable. But there is a danger:

```text
R4 = 63 / 21 / ±1 / 0
       ↓
test 40 × 40 × 20 combinations
       ↓
find attractive region
       ↓
"Oh, R4 is robust"
```

We have just created another multiple-testing problem. Pardo's WFA methodology explicitly deals with optimization, OOS evaluation, robustness and overfitting rather than simply searching historical parameter combinations.

So the framework should be:

```text
FROZEN R4
   │
   ├── historical specification
   │
   └── PARAMETER ROBUSTNESS STUDY
           │
           ├── pre-registered grid
           ├── bounded perturbations
           ├── WFA
           ├── OOS
           ├── multiple testing
           └── stability metrics
```

And the output should **not** be:

> "Optimal R4 parameters are X."

It should be:

> "The frozen configuration lies inside/outside a region of historically stable configurations."

That is a much more scientifically defensible result.

---

## 4. Meta-Labeling Should NOT Be Experiment #1

This is the biggest sequencing change. The audit proposes:

```text
R4 → triple barrier → meta model
```

Good architecture. But before building the model, build:

```text
R4 → triple-barrier labeling engine → label quality / uniqueness analysis
   → baseline statistics → feature laboratory → ONLY THEN meta-label model
```

Otherwise we immediately get "let's find features that predict the label" — exactly where feature/data-mining complexity can explode.

The correct progression:

- **Stage A** — Can we construct valid labels?
- **Stage B** — Do the labels contain predictable structure?
- **Stage C** — Which existing features explain that structure?
- **Stage D** — Does ML add information beyond simple baselines?
- **Stage E** — Does that information survive OOS + costs + regimes?
- **Stage F** — Only then: could it affect take/skip/size?

Chan's book similarly emphasizes systematic strategy development and implementation rather than simply throwing a more sophisticated model at a trading problem.

---

## 5. The Factor Laboratory Is Actually Foundational

Move this **ahead of meta-labeling**. The current architecture already has:

```text
Feature Registry / Feature Contracts / Feature Families / Availability timestamps
```

That is a strong foundation. The missing layer is:

```text
FEATURE → does it contain information? → IC / Rank IC → quantiles
        → turnover → cost → regimes → OOS → incremental portfolio contribution
```

That gives a disciplined answer to "Is this feature actually useful?" rather than "Can an ML model somehow use this feature?"

---

## 6. Mean Reversion / Stat-Arb Is Legitimate — But Don't Start With Pairs

Chan's material strongly supports a separate research family around stationarity, ADF, cointegration, hedge ratios and half-life. But the audit's proposed initial universe is too broad:

> EURUSD/GBPUSD, AUDUSD/NZDUSD, EUR crosses, CAD/commodity, indices ...

Start with a **small preregistered universe**:

```text
AUDUSD / NZDUSD
EURUSD / GBPUSD
```

Then establish the pipeline:

```text
candidate pair → point-in-time cointegration → hedge ratio → spread
→ half-life → entry/exit → cost → WFA → OOS
```

Only if that works should the candidate universe expand.

Also, **do not** require "performance comparable to R4" as an automatic promotion criterion. That is too arbitrary. A stat-arb strategy may have:

- lower standalone return
- lower correlation
- different drawdown timing
- different tail behavior

and still be valuable at the portfolio level. The better promotion question is:

> **Does the strategy demonstrate statistically and economically credible OOS behavior and provide incremental portfolio utility after costs?**

---

## 7. Order-Flow Entropy Should Probably Be Postponed

The audit's framing is conceptually good: entropy is infrastructure, not alpha. But there is a more important issue: **do we actually have the data?**

If EigenCapital currently operates primarily on OHLC/market data, then order-flow entropy requires:

```text
trade sequence / trade direction / trade activity / possibly bid-ask-depth
```

Do not build:

```text
OHLC → fake order-flow → entropy
```

That is exactly the kind of synthetic sophistication we want to avoid.

So mark it: **BLOCKED — DATA DEPENDENCY** until the data contract exists. Davey's material itself emphasizes that inappropriate or poor-quality market data can invalidate strategy testing, which reinforces this restraint.

---

## 8. Strategy-Level Portfolio Construction Is Missing From the Six — And Should Stay Deferred

The audit identifies strategy-level portfolio construction as a major gap, but the six "smallest changes" don't include it. That is fine **if intentional** — and it should be intentional/deferred.

There are not yet enough validated independent strategy families to justify making strategy-level allocation a major engineering project. Right now:

- **R4** is the mature production strategy.
- Mean reversion/stat-arb is still research.
- Meta-labeling is still research.

So strategy-level ERC becomes useful **after** at least one or two additional strategy families survive validation. Otherwise we are building a portfolio allocator for strategies that don't exist yet.

---

## 9. Revised Roadmap: R0–R8

The actual EigenCapital research progression replaces the audit's six flat experiments:

### R0 — Research Infrastructure Verification

No major code. Verify:

- experiment registry
- hypothesis registry
- trial counting
- feature availability
- cost model
- WFA
- purging/embargo
- multiple-testing
- provenance

Only patch actual gaps.

### R1 — Monte Carlo Diagnostics

**First implementation.**

- **Input:** existing historical trade streams
- **Output:** trade-order distributions, drawdown distributions, losing streaks, recovery times, terminal wealth, tail scenarios
- No production impact.

### R2 — Alpha Factor Laboratory

Build the measurement layer:

```text
feature → IC → Rank IC → quantiles → turnover → cost → regime → OOS → incremental contribution
```

This becomes the foundation for later ML.

### R3 — Parameter Stability

Now study the R4 candidate parameter neighborhood, but with:

- preregistered grid
- WFA
- OOS
- multiple-testing correction
- stability metrics

No R4 modification.

### R4-stage — Mean Reversion / Stat-Arb

Small initial universe. Start with perhaps:

```text
AUDUSD/NZDUSD
EURUSD/GBPUSD
```

Then expand only if justified. Chan specifically covers stationarity, cointegration, ADF/CADF/Johansen, hedge ratios and half-life, so this is a legitimate separate research family rather than an arbitrary addition.

### R5 — Triple Barrier

Now that the factor laboratory exists:

```text
R4 side → triple barrier → label diagnostics → feature evaluation
```

Still **no ML initially**.

### R6 — Meta-Labeling

Only after R5 produces valid labels:

```text
R4 → triple-barrier labels → baseline classifier → ML candidates → OOS → incremental value
```

Baseline hierarchy:

```text
Baseline 0: R4
Baseline 1: simple deterministic filter
Baseline 2: logistic regression
Baseline 3: tree model
...
```

If logistic regression cannot add value, there is no reason to jump to a sophisticated ensemble.

### R7 — Order-Flow Entropy

Only if data becomes available:

```text
DATA CONTRACT → trade sequence → entropy → regime classification
→ incremental information → shadow gating
```

Then compare:

```text
R4  vs  R4 + existing regime gate  vs  R4 + entropy gate
```

That is the proper experiment.

### R8 — Strategy-Level Portfolio

Only after:

```text
R4 + validated MR/stat-arb + possibly validated meta-strategy
```

Then:

```text
strategy returns → strategy covariance → drawdown overlap → tail dependence → ERC → allocation
```

---

## 10. The Real "Smallest Set" Is Actually Smaller

If freezing the roadmap today, reduce to:

### Tier 1 — Build now

1. **Monte Carlo Diagnostic Framework**
2. **Alpha Factor Laboratory**
3. **Parameter Stability Framework**

These are infrastructure/methodology improvements that can immediately consume existing EigenCapital research outputs.

### Tier 2 — Research next

4. **Mean-Reversion / Stat-Arb Family**
5. **Triple-Barrier Labeling**

### Tier 3 — Conditional (explicit prerequisites)

6. **Meta-Labeling** — requires R5 valid labels
7. **Order-Flow Entropy** — requires data contract
8. **Strategy-Level Portfolio Construction** — requires ≥1 additional validated strategy family

---

## 11. Removed From the Report

This statement is too strong and is **removed**:

> "R4 signal design is sound"

The books can support:

> **R4's methodology is consistent with established systematic trend/momentum research practices.**

They cannot establish that R4 is profitable, robust, or "sound" in the investment sense. Likewise:

- "volatility-normalized cumulative return / momentum Z-score with 63/21 lookbacks aligns with multiple sources" — **okay as a methodological observation**
- "R4 is validated by the books" — **not okay**

The books provide **methodological support, not empirical validation** of the implementation.

---

## 12. Correction to the Final Paragraph

The audit concludes:

> "without introducing overfitting risk"

**Change that.** We cannot guarantee that. The initiatives **introduce opportunities for additional overfitting**, particularly:

- factor laboratory
- parameter surfaces
- triple barriers
- meta-labeling
- stat-arb pair discovery

What we can say is:

> **They are designed to control and measure additional overfitting risk rather than ignoring it.**

That is much stronger scientifically.

---

## 13. Final Architecture to Freeze

```text
                         ┌──────────────────────┐
                         │     MARKET DATA      │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │   DATA CONTRACTS     │
                         │ PIT / VERSIONING     │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │   FEATURE LIBRARY    │
                         │ versioned / PIT      │
                         └──────────┬───────────┘
                                    │
             ┌──────────────────────┼──────────────────────┐
             │                      │                      │
             ▼                      ▼                      ▼
      Factor Lab              Alpha Research          R4 Research
             │               ┌──────┴──────┐               │
             │               │             │               │
             ▼               ▼             ▼               ▼
          IC/OOS          MR/Stat-Arb   Triple Barrier   Parameter
          Cost            research      labels           stability
          Regime
             │                              │
             │                              ▼
             │                         Meta-labeling
             │                              │
             └──────────────┬───────────────┘
                            │
                            ▼
                   ┌──────────────────┐
                   │ STRATEGY LAYER   │
                   │ R4 = FROZEN      │
                   │ MR = research    │
                   │ ML = research    │
                   └────────┬─────────┘
                            │
                            ▼
                   ┌──────────────────┐
                   │ PORTFOLIO LAYER  │
                   │ correlation      │
                   │ covariance       │
                   │ ERC              │
                   │ exposure         │
                   └────────┬─────────┘
                            │
                            ▼
                   ┌──────────────────┐
                   │   EIGENRISK      │
                   │  FAIL-CLOSED     │
                   └────────┬─────────┘
                            │
                            ▼
                   ┌──────────────────┐
                   │    EXECUTION     │
                   │ PAPER / LIVE     │
                   └────────┬─────────┘
                            │
                            ▼
                   ┌──────────────────┐
                   │ EVIDENCE / AUDIT │
                   │ WFA / MC / OOS   │
                   │ TRIALS / PROV.   │
                   └──────────────────┘
```

And separately:

```text
                 ORDER-FLOW ENTROPY
                        │
                 DATA AVAILABLE?
                   /          \
                 NO            YES
                 │              │
             BLOCKED      Research only
                                │
                                ▼
                         Regime experiment
                                │
                                ▼
                           Shadow gate
                                │
                                ▼
                              OOS
```

---

## Bottom Line

**The audit is directionally correct and quite strong.** The main change is the sequencing.

Do not now go: "Great, let's create six directories and start coding." Instead:

> **Monte Carlo → Factor Laboratory → Parameter Stability → Mean Reversion → Triple Barrier → Meta-labeling → Entropy if data exists → Strategy Portfolio.**

That sequence keeps EigenCapital's existing architecture intact while progressively creating the evidence needed for the next layer. It is consistent with what the source material actually emphasizes: Pardo's focus on OOS/WFA and robustness, Chan's systematic treatment of mean reversion/cointegration, and Davey's progression from testing through Monte Carlo and incubation.

**This revised research roadmap is frozen before writing any new production code.**

---

## 14. Frozen Stage-Boundary Table

The roadmap is a **research queue, not an architecture invitation**. Each stage has one primary purpose and exactly one promotion path: research evidence → candidate strategy → validation → promotion. Never: research experiment → production modification.

| Stage | Primary purpose | Can modify R4? |
|-------|-----------------|---------------:|
| R0 | Verify research infrastructure | **No** |
| R1 — Monte Carlo | Quantify path/risk uncertainty | **No** |
| R2 — Factor Lab | Discover/test candidate explanatory features | **No** |
| R3 — Parameter Stability | Test robustness of frozen/candidate configurations | **No** |
| R4-stage — MR / Stat-Arb | Develop separate alpha family | **No** |
| R5 — Triple Barrier | Improve event/label definition | **No** |
| R6 — Meta-labeling | Conditional trade-selection research | **No** |
| R7 — Entropy | Conditional microstructure research | **No** |
| R8 — Strategy Portfolio | Combine **validated** families | **No** |

Only a **separate, explicitly approved promotion process** ever turns research output into production strategy behavior.

The literature audit is now evidence about **how EigenCapital should research**, not evidence that R4 itself needs redesign. Parameter stability asks whether the frozen configuration sits inside a historically stable region — never "optimal parameters." Monte Carlo remains a **conditional diagnostic of the observed strategy/trade process**, not a prediction engine.

---

## 15. R0 Handoff

**Next engineering task: R0 — Research Infrastructure Verification.**

R0 inspects the *existing* EigenCapital research machinery against the frozen R0–R8 requirements and produces a very small gap list with exactly four classifications:

- **PASS** — already exists and is adequate
- **PATCH** — demonstrable deficiency
- **BLOCKED** — missing prerequisite/data
- **DEFERRED** — intentionally later

Verification scope (from R0 definition, §9): experiment registry, hypothesis registry, trial counting, feature availability, cost model, WFA, purging/embargo, multiple-testing, provenance.

Then, if R0 finds no material defects, proceed directly to **R1 — Monte Carlo**. Not another literature review. Not another architecture redesign. Not another R4 modification.
