# Quorrin — Architecture Foundations

## Status: Locked

This document defines the architectural invariants discovered through 9 months of systematic research across FX, crypto (BTC), and commodities (GC). These are not design preferences — they are empirically derived theorems about where alpha lives in this system class. Future work that violates these invariants should be treated as hypothetical until proven otherwise.

---

## Theorem 1: Three-Layer Decomposition

The system decomposes into three causally independent layers. Each layer has a distinct role, a distinct bottleneck, and a distinct empirical behavior.

### Layer A — Representation (feature space)

**Role:** Project raw market data into a learnable space.

**Components:** FeatureContract system, Driver Atlas, regime classifier features (KER, ADX, vol z-score).

**Empirical behavior:**
- Transferable across FX, BTC, and GC without modification
- 4 shared features (rate_diff, dxy_mom, vix_ma, vix_delta) produce nonzero signal on BTC via FX-trained model (SR=0.44)
- 10-feature BTC-specific expansion does not degrade transfer performance
- Feature count above ~10 provides no marginal benefit; the system is not feature-limited

**Invariant:** *Representation is general.* Any asset with price, macro, and vol data can be projected into this space without retraining the feature layer.

---

### Layer B — Labeling (target definition)

**Role:** Define what "structure" means for the supervised learner.

**Empirical behavior:**
- **Dominant source of performance variance** across all tests
- BTC: tb-vol labels → SR ~0.5
- GC: forward-return labels (120-bar) → SR ~2.9
- FX: tb20 labels → SR ~1.5–2.0 for promoted assets
- The same model architecture, same feature set, same execution geometry produce results ranging from "no edge" to "production-ready" depending solely on label choice

**Invariant:** *Alpha is not discovered by the model. Alpha is projected onto the model by the labeling function.* The model learns whatever structure the label defines. If the label does not align with the asset's latent dynamics, the model produces noise regardless of feature quality, model capacity, or execution tuning.

**Corollary:** The system is not learning "price movement." It is learning the specific projection of price movement defined by the labeling function. Comparing models trained with different labels is not comparing model quality — it is comparing projection quality.

---

### Layer C — Execution Geometry (SL/TP)

**Role:** Extract value from the projected signal.

**Empirical behavior:**
- FX: medium geometry (sl=0.75, tp=2.25) optimal — tight (0.3) breaks training via label imbalance, loose (1.5) leaves 30–50% Sharpe on the table
- BTC: tight geometry (sl=0.3, tp=3.0) optimal — SR=1.007 vs 0.515 for medium
- GC: tight geometry (sl=0.3, tp=2.25) optimal — SR=2.901 vs 1.512 for medium
- Tight SL universally dominates for non-FX assets; medium is FX-specific

**Invariant:** *Geometry amplifies or attenuates an existing structure. It does not create structure.* The best geometry at SR=2.9 (GC) cannot rescue a broken label (BTC at SR=0.5). The worst geometry at SR=1.0 (BTC tight) still outperforms the wrong label at any geometry.

**Corollary 1:** Geometry selection is a function of asset noise structure, not of prediction quality. High-noise / high-vol regimes (BTC, GC) require tight stops to survive microstructure noise. Lower-noise regimes (FX) tolerate wider stops and benefit from the structural microstructure noise balance.

**Corollary 2:** Optimizing geometry before confirming label-asset alignment is premature optimization. Geometry should be set after the label projection is validated, not before.

---

## Theorem 2: Causal Chain

Alpha flows through the system in exactly one direction:

```
Asset physics → label projection → model training → geometry conditioning → P&L
```

Each step can only degrade the signal. No step can create signal that was not present in the previous step.

- If the label is misaligned (Step 2), no model or geometry can recover alpha.
- If the label is aligned but the model is undertrained (Step 3), the signal degrades but is structurally recoverable.
- If the label and model are correct but the geometry is wrong (Step 4), the signal degrades by a known, measurable factor (typically 30–50% of achievable Sharpe).

**Operational implication:** Debugging a failed asset starts at Step 2, never at Step 3 or 4. If the label is correct, the model will find the structure. If the model cannot find structure, the label is wrong.

---

## Theorem 3: Three Expansion Axes

During the research pipeline (Phases D–G), three independent directions were tested for cross-sectional improvement inside FX:

| Axis | Phase | Result | Status |
|------|-------|--------|--------|
| Confidence calibration | D | ECE 0.20→0.04, but calibrated probabilities compress to ~50% | **Dead** — no discriminatory power |
| Outcome magnitude (MFE/MAE) | E | XGBoost regressor; Pearson r ≈ confidence r | **Dead** — no orthogonal signal in current feature basis |
| Persistence (signal survival) | G | XGBoost classifier; r up to 0.51 for GBPUSD at k=15 | **Execution-orthogonal** — real feature signal, zero operational value for conditioning or filtering |

**Invariant:** *The current feature basis is saturated for cross-sectional improvement inside FX-like structure.* All three expansion directions converge to structural null. No fourth direction is likely to produce a different result without a fundamentally different feature set or modeling approach.

**Operational implication:** Within FX, performance is determined by asset selection (which assets have stable label-asset alignment) and geometry selection, not by adding model complexity or secondary prediction heads.

---

## Theorem 4: Generalization Boundaries

Tested in Phase H across BTC (endogenous vol, reflexive order flow) and GC (macro drift, long-horizon trend).

| Property | Generalizes? | Evidence |
|----------|-------------|----------|
| Feature representation | ✔ Yes | FX features produce SR=0.44 on BTC with zero retraining |
| XGBoost model architecture | ✔ Yes | Same pipeline works on all three asset classes |
| Regime detection (transition structure) | ✔ Yes | Positive SR from domain models on both BTC and GC |
| Label function (tb20) | ✗ No | FX label (tb20) does not generalize; BTC needs tb-vol, GC needs forward-return |
| Execution geometry (medium) | ✗ No | FX optimum (0.75/2.25) is wrong for BTC and GC; tight SL (0.3) dominates universally outside FX |

**Invariant:** *The architecture generalizes. The parameterization does not.* Any attempt to deploy on a new asset class must recalibrate (a) the labeling function and (b) the geometry. The feature representation and model architecture can be transferred unchanged.

---

## Theorem 5: Stopping Condition

The research pipeline is complete when all three expansion axes and the generalization boundary have been tested, and the empirical decomposition matches the theoretical decomposition.

**For Quorrin, this condition is met:**

- ✔ Representation layer: tested and generalizable (FX, BTC, GC)
- ✔ Labeling layer: identified as dominant control knob; three distinct label types characterized
- ✔ Execution layer: characterized as secondary conditioner; geometry-asset mapping established
- ✔ All expansion axes tested: calibration (dead), outcome magnitude (dead), persistence (execution-orthogonal)
- ✔ Generalization boundary: architecture generalizes, parameterization does not

**Any further work is either:**
- **Stabilization** (observe live engine, confirm assumptions hold in production)
- **New research direction** (unified labeling theory, adaptive geometry)

> **Note:** A meta-label generator now exists (`labels/meta_labels.py:MetaLabelModel`, XGBoost-based) — replaces the earlier LogisticRegression approach that failed to outperform random.

---

## Empirical Summary Table

| Asset | Label Type | Model | Best SL/TP | Max SR | Replay SR (medium) |
|-------|-----------|-------|------------|--------|-------------------|
| EURAUD | tb20 | FX-trained | 0.75/2.25 | ~2.0* | ~1.8* |
| USDCAD | tb20 | FX-trained | 0.75/2.25 | ~2.1* | ~1.9* |
| NZDJPY | tb20 | FX-trained | 0.75/2.25 | ~1.7* | ~1.5* |
| AUDJPY | tb20 | FX-trained | 0.75/2.25 | ~1.6* | ~1.4* |
| USDCHF | tb20 | FX-trained | 0.75/2.25 | 2.33 | 1.82 |
| GBPUSD | tb20 | FX-trained | 1.0/2.5 | 1.82 | 0.72† |
| BTC | tb-vol | 10-feature | 0.3/3.0 | 1.01 | 0.52 |
| GC | fwd120 | 4-feature | 0.3/2.25 | 2.90 | 1.51 |

*Retrain report estimates. †Loose collapse — monitor asset, not portfolio asset.
Static SL/TP values shown are research-optimized historical baselines. Live system uses ATR-based dynamic barriers via `shared/volatility.py:VolatilityPrimitive` — see `configs/paper_trading.yaml` for per-asset ATR parameters.

---

## Theorem 6: Execution Pipeline Decomposition

The system's execution path decomposes into four causally isolated sub-layers, discovered during the Execution Research Framework (Phases 0–6). Each sub-layer has a distinct role, a distinct bottleneck, and a distinct empirical constraint.

### Sub-layer A — Archetype Classification (Phase 3)

**Role:** Project signal state into discrete market-structure archetype.

**Components:** `features/archetypes.py` — 5 pure-feature archetypes (BREAKOUT, TREND_PULLBACK, MEAN_REVERSION, VOLATILITY_EXPANSION, MOMENTUM_IGNITION).

**Constraint:** *Archetype is a projection of feature space, not model inference.* It adds no information beyond what is already present in the feature vector. It restructures existing information into a decision-relevant taxonomy.

**Invariant:** *Archetype classifies what the model already sees.* It cannot create edge; it can only route to an appropriate policy.

---

### Sub-layer B — Entry Quality (Phase 1)

**Role:** Gate entry on timing quality.

**Components:** `EntryOptimizer` (ENTER / DEFER / SKIP), `DeferredEntry` (idempotent entry_id, PENDING/TRIGGERED/EXPIRED/CANCELLED state machine).

**Constraint:** *DeferredEntry is execution state, not temporary calculation.* It must persist across ticks. The idempotent entry_id (hash of signal_snapshot + symbol + timestamp_bucket) prevents double-trigger on restart or replay.

**Invariant:** *Entry quality can only degrade the signal.* It can defer or skip, but never improve a weak signal into a strong one.

---

### Sub-layer C — Fill Realism (Phase 5)

**Role:** Emulate market physics at fill time.

**Components:** `ExecutionSimulator`, `SlippageModel`, `FillModel`, `LatencyModel`.

**Constraint:** *Fill realism sits after PolicyDecision freeze.* The decision is finalized before physics is applied. Phase 5 may only degrade outcomes, never improve them.

**Invariant:** *Execution randomness is deterministic.* Same seed + same inputs → identical FillResult across runs. All sub-components use seeded RNG: SlippageModel(seed), FillModel(seed+1), LatencyModel(seed+2).

**Corollary:** *Fill asymmetry is structural, not random.* SL fills get adverse slippage (1.5× base); TP fills get neutral/near-zero slippage (0.1× base). This reflects documented market microstructure: stop-losses cluster and gap, while limit orders provide liquidity.

---

### Sub-layer D — Trade Attribution (Phase 6)

**Role:** Observe, diagnose, and decompose execution outcomes into causally distinct components.

**Components:** `AttributionCollector`, `PredictionAttribution`, `ExecutionAttribution`, `ExitAttribution`, `FrictionAttribution`.

**Constraint:** *Phase 6 observes everything, mutates nothing.* Analytics never feed back into labels, frozen kernel, or policies. The attribution layer is epistemically isolated from all decision and execution layers.

**Invariant:** *Four-domain attribution is irreducible.* A single collapsed PnL number conflates prediction accuracy, execution quality, exit timing, and market friction. These four domains are causally independent and must be tracked separately for diagnostic value.

**Corollary:** *Counterfactual metrics are diagnostic, not predictive.* What-if scenarios (perfect entry, zero slippage, ideal exit) reveal where alpha is lost in the pipeline, but cannot be used to retroactively improve outcomes.

---

### Updated Causal Chain

The original Theorem 2 causal chain is extended to include the execution pipeline:

```
Asset physics → label projection → model training → geometry conditioning
    → archetype classification → entry quality → policy decision
    → fill realism → attribution (observe only)
    → P&L
```

Each step can only degrade the signal (except attribution, which neither degrades nor improves). No step can create signal that was not present in the previous step.

After geometry conditioning, the remaining degradation sources are:
- **Archetype misclassification** (~5–15% of remaining expectancy)
- **Entry timing error** (deferred vs immediate, ~5–20% depending on archetype)
- **Slippage + fill cost** (measured empirically via Phase 6 attribution, typically 10–30% of gross alpha)
- **Exit quality** (MAE/MFE decomposition reveals exit efficiency)

---

*Document locked May 2026. No revisions without empirical contradiction.*
