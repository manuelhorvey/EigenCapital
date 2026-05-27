# QUANTFORGE

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Status](https://img.shields.io/badge/status-research%20system%20%7C%20paper%20trading-green)
![WalkForward](https://img.shields.io/badge/walk--forward-32%20assets%20validated-success)
![Portfolio](https://img.shields.io/badge/portfolio-14%20assets%20%7C%20BTC%20satellite-blue)
[![codecov](https://codecov.io/gh/manuelhorvey/QuantForge/graph/badge.svg)](https://codecov.io/gh/manuelhorvey/QuantForge)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## 1. SYSTEM OVERVIEW

QuantForge is a **deterministic market interaction simulator with causally decomposed execution quality** — an adaptive multi-asset research platform combining governance-driven execution control, stress-conditioned survival modeling, and an immutable execution contract ledger.

| Layer | Purpose |
|-------|---------|
| **Features** | Deterministic macro-conditioned signals under strict schema contracts |
| **Models** | Probabilistic directional intent via XGBoost (BUY / HOLD / SELL) — signal generator, not decision authority |
| **Archetype Classification** | 5 pure-feature market structure archetypes — primary execution conditioning variable across Phases 1-4 |
| **Entry Quality** | DeferredEntry engine with idempotent entry_id, EntryOptimizer routing (ENTER / DEFER / SKIP) |
| **Execution Policy** | Immutable PolicyDecision dispatch — archetype-to-policy switchboard |
| **Fill Realism** | Seeded deterministic slippage (asymmetric SL/TP), gap-through, partial fill, latency |
| **Trade Attribution** | 4-domain causal reconstruction (Prediction, Execution, Exit, Friction) with counterfactual decomposition — observes everything, mutates nothing |
| **Governance** | 7-layer suppression under instability — see [docs/GOVERNANCE_LAYER.md](docs/GOVERNANCE_LAYER.md) |
| **Simulation** | Adversarial survival testing with execution physics and deleveraging feedback |
| **Execution** | Paper trading with mark-to-market PnL, SL/TP surface optimization, portfolio construction |
| **Telemetry** | Shadow analytics, drift detection, importance tracking, deterministic replay |

### Design Philosophy

- **Execution realism over nominal CAGR** — simulated fills, spread expansion, gap risk, partial fill decay
- **Survival under stress over historical fit** — adversarial perturbation, not backtest R²
- **Governance as primary component** — validity state machines, stability penalties, meta-labeling, narrative + liquidity governance
- **Portfolio topology over standalone alpha** — assets selected for marginal contribution to portfolio risk, not individual Sharpe
- **Archetypes as primary routing key** — execution policy, TP geometry, and entry behavior are all conditioned on archetype classification; archetypes are the central conditioning variable across Phases 1-4
- **Epistemic boundary separation** — prediction (Phase 3), decision (Phase 4), execution (Phase 5), and attribution (Phase 6) are causally isolated layers; each can only degrade the signal, never create it
- **Fill realism as degradation** — Phase 5 may only make fills worse, never better; sits after PolicyDecision freeze
- **Observe-only analytics** — Phase 6 attribution observes everything but mutates nothing; never feeds back into labels, frozen kernel, or policies

---

## 2. ARCHITECTURE

```mermaid
graph TD
A[Market + Macro Data] --> B[FeatureContract Validation]
B --> C[Driver Atlas Routing]
C --> D1[JPY Carry: NZDJPY / AUDJPY / GBPJPY / CHFJPY]
C --> D2[USD Macro: USDCAD / USDCHF / GBPUSD / USDJPY]
C --> D3[Real Yield: GC=F]
C --> D4[Equity Index: ^DJI]
C --> D5[EUR Cross: EURAUD / EURCAD]
C --> D6[Oil-Correlation: CADJPY]
C --> D7[BTC Satellite: HighVolSatellite]

D1 & D2 & D3 & D4 & D5 & D6 --> E[Labeling Layer]
D7 --> S[Satellite Gate]
S --> E

E --> F1[tb20: Triple Barrier]
E --> F2[fwd60: Forward Returns]
F1 & F2 --> G[XGBoost Signal Generator]
G --> H[Regime Classifier Overlay]
G --> I[Signal Intent]
H --> I
I --> J[Risk Engine]
J --> K[Portfolio Allocation]

K --> P[Execution Spine: Phases 3-6 — see detailed pipeline below]
P --> L[PaperBroker Execution]
L --> M[Observability Layer]

subgraph "Research (Offline)"
    R1[Execution Surface Sweep]
    R2[Survival Monte Carlo]
    R3[Regime Bootstrap]
    R1 & R2 & R3 --> R[Research / Risk]
end
R --> A
```

### Execution Pipeline (Phases 3–6)

```mermaid
graph LR
    subgraph Signal [Signal Layer]
        A[Model Signal + Confidence] --> B[Archetype Classifier]
    end

    subgraph Entry [Entry Quality]
        B --> C[EntryOptimizer]
        C --> D{EntryAction}
        D -->|ENTER| E[PolicyDecision Builder]
        D -->|DEFER| F[DeferredEntry]
        D -->|SKIP| G[Skip Signal]
    end

    subgraph Policy [Execution Policy — FROZEN CONTRACT]
        E --> H[POLICY_MAP Dispatch]
        H --> I[PolicyDecision: immutable]
        F -->|Triggered| E
    end

    subgraph Fill [Fill Realism — FROZEN CONTRACT]
        I --> J[ExecutionSimulator]
        J --> K[SlippageModel: asym SL/TP]
        J --> L[FillModel: gap-through]
        J --> M[LatencyModel: seeded delay]
        K & L & M --> N[FillResult: immutable]
    end

    subgraph Attribute [Causal Reconstruction — FROZEN CONTRACT]
        N --> O[AttributionCollector: observe-only]
        O --> P[Prediction Attribution]
        O --> Q[Execution Attribution]
        O --> R[Exit Attribution]
        O --> S[Friction Attribution]
    end

    subgraph State [State Mutation — Mutable]
        N --> T[AssetEngine: position state]
        T --> U[PnL + Journal + Snapshots]
    end

    style I fill:#1a1a2e,stroke:#e94560
    style O fill:#1a1a2e,stroke:#0f3460
    style N fill:#16213e,stroke:#e94560
```

See [docs/SYSTEM_OVERVIEW.md](docs/SYSTEM_OVERVIEW.md) for full component details.

---

## 3. GETTING STARTED

```bash
git clone https://github.com/user/quantforge.git && cd quantforge
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export FRED_API_KEY=your_key
./monitor_all                              # build frontend + start engine + dashboard
# Dashboard: http://localhost:5000
```

**Rebuild frontend after UI changes:** `(cd paper_trading/dashboard && yarn build)` — 24 components, sortable DataTable, Recharts charts, anchor nav
**Run tests:** `pytest tests/ -q --tb=short`

### Environment

| Var | Required | Purpose |
|-----|----------|---------|
| `FRED_API_KEY` | Yes | Macro data (yields, VIX, DXY) |
| `OPENCODE_ZEN_API_KEY` | No* | Weekly LLM narrative extraction |
| `PYTHONPATH` | Yes | `PYTHONPATH=.` |
| `QUANTFORGE_REFRESH_INTERVAL` | No | Engine loop interval (default 300s) |

*\*Without OPENCODE_ZEN_API_KEY, narrative governance skips LLM call and uses neutral defaults.*

---

## 4. LIVE PORTFOLIO

13-asset continuously evaluated simulation with regime-optimized SL/TP (sl=0.30, sweep-derived TP per asset). BTC actively traded in a satellite bucket via a 5-condition macro gate with vol-adjusted SL/TP and full position management — opens when gate permits, closes when gate blocks or SL/TP is hit, with entry/target/stop prices and exit reasons exposed on the dashboard.

| Asset | Alloc | sl_mult | tp_mult | R:R | Scale-out | Regime-tuned |
|-------|-------|---------|---------|:---:|-----------|--------------|
| EURAUD | 12% | 0.30 | 1.00 | 1:3.3 | 4-tier | yes |
| GC | 13% | 0.30 | 1.50 | 1:5.0 | no | yes |
| NZDJPY | 11% | 0.30 | 1.75 | 1:5.8 | 4-tier | yes |
| CADJPY | 9% | 0.30 | 1.25 | 1:4.2 | 4-tier | yes |
| USDCAD | 8% | 0.30 | 1.50 | 1:5.0 | 4-tier | yes |
| GBPJPY | 8% | 0.30 | 1.25 | 1:4.2 | 4-tier | yes |
| CHFJPY | 7% | 0.30 | 1.00 | 1:3.3 | no | yes |
| AUDJPY | 6% | 0.30 | 1.75 | 1:5.8 | 4-tier | yes |
| EURCAD | 5% | 0.30 | 1.75 | 1:5.8 | 4-tier | yes |
| ^DJI | 5% | 0.30 | 1.50 | 1:5.0 | 4-tier | yes |
| GBPUSD | 5% | 0.52 | 1.97 | 1:3.8 | 4-tier | no |
| USDJPY | 4% | 0.30 | 1.00 | 1:3.3 | no | yes |
| USDCHF | 4% | 0.30 | 1.75 | 1:5.8 | 4-tier | yes |

**BTC satellite**: 5% AUM cap, vol target 40%, drawdown limit 25%, 5-condition AND gate. Actively managed — positions open on gate OPEN, close on gate CLOSED or SL/TP hit. Vol-adjusted SL/TP (same formula as core assets: `entry × (1 ± vol × multiplier)`). Entry/stop/target prices and exit reason logged per cycle and displayed on the satellite dashboard card.

> Portfolio allocation provides capital input only. Execution truth resides in the deterministic contract chain: PolicyDecision (Phase 4) → FillResult (Phase 5) → AttributionRecord (Phase 6). Allocation weights are not execution decisions.

---

## 5. KEY CONFIGURATION

Reference for `configs/paper_trading.yaml`. See [docs/PAPER_TRADING_RUNBOOK.md](docs/PAPER_TRADING_RUNBOOK.md) for full details.

| Key | Default | Description |
|-----|---------|-------------|
| `capital` | 100000 | Starting capital |
| `position_size` | 0.95 | Capital utilization cap |
| `halt.drawdown` | -0.08 | Per-asset drawdown halt |
| `portfolio_drawdown_limit` | -0.15 | Portfolio circuit breaker |
| `narrative_config.enabled` | true | Weekly macro narrative |
| `narrative_config.geopol_sl_widen_pct` | 10 | SL widen on geopol risk > 0.7 |
| `narrative_config.risk_off_size_reduce_pct` | 20 | Size reduce on risk_off |
| `narrative_config.min_confidence` | 0.6 | Min LLM confidence |
| `liquidity_config.enabled` | true | Per-tick liquidity regime |
| `liquidity_config.volume_z_thin_threshold` | -1.5 | Volume z → THIN |
| `liquidity_config.amihud_high_threshold` | 1.5 | Amihud z → THIN |
| `liquidity_config.stressed_sl_widen_pct` | 30 | SL widen in STRESSED |
| `meta_labeling.confidence_threshold` | 0.40 | Primary signal confidence filter (isotonic calibrated) |
| `meta_labeling.threshold_reduced` | 0.40 | Meta-model REDUCED/SKIP boundary |

---

## 6. GOVERNANCE LAYERS

| Layer | Frequency | Scope | Effect | Docs |
|---|---|---|---|---|
| Validity state machine | Per tick | Per asset | Exposure 0–100% | — |
| Feature stability | Per retrain | Per asset | Validity penalty | — |
| Meta-labeling | Per signal | Per asset | Trade skip | — |
| Macro narrative | Weekly | Global | SL +10%, size −20% | `features/macro_narrative.py` |
| Liquidity regime | Per signal | Per asset | SL +15/30%, size −15/30%, halt | `features/liquidity_regime.py` |
| PSI drift | Per cycle | Per asset | Validity penalty, halt at 3+ SEVERE | `monitoring/psi_monitor.py` |

Multiplicative chain: `final_sl = base × regime_geom × narrative_sl × liquidity_sl`  
Validity stacking: stability penalty + PSI penalty + halt penalties (additive, worst-wins at layer level)

Full detail: [docs/GOVERNANCE_LAYER.md](docs/GOVERNANCE_LAYER.md)

---

## 7. FEATURE ENGINEERING

FeatureContract system enforces deterministic train/serve parity with cross-asset isolation. 13 feature modules produce macro-conditioned signals under strict schema contracts. Driver atlas routes per-asset feature subspaces.

Full detail: [docs/FEATURES.md](docs/FEATURES.md)

---

## 8. MODEL ARCHITECTURE

**XGBoost** multiclass classifier (BUY / HOLD / SELL) with 300 trees, max_depth=2, learning_rate=0.02 — serves as **probabilistic signal generator**, not decision authority. Optional macro expert head with adaptive blend weight. Strategy interfaces via `shared/` abstract base classes.

The model produces directional intent; execution truth is resolved downstream by the structural decision spine: Archetype Classification (Phase 3) → Entry Optimizer (Phase 1) → Execution Policy (Phase 4) → Fill Realism (Phase 5) → Attribution (Phase 6). Model output is one of several inputs to the archetype-conditioned policy layer — never a direct trading decision.

Full detail: [docs/ARCHITECTURE_FOUNDATIONS.md](docs/ARCHITECTURE_FOUNDATIONS.md)

---

## 9. HARDENING ROADMAP

### Execution Research Framework (Phases 0–6)

| Phase | Capability |
|-------|------------|
| **0** | Frozen Kernel + Labels — retrained with runtime-consistent initial geometry; no adaptive logic leaks into labels |
| **1** | Entry Quality Engine — EntryOptimizer, DeferredEntry with idempotent entry_id |
| **2** | TP/Exit Geometry — regime×archetype TP compiler; backloaded scale-out tiers per archetype |
| **3** | Archetype Classification — 5 pure-feature archetypes: BREAKOUT, TREND_PULLBACK, MEAN_REVERSION, VOLATILITY_EXPANSION, MOMENTUM_IGNITION |
| **4** | Execution Policy Layer — archetype-to-policy dispatch via POLICY_MAP; PolicyDecision as immutable instruction packet |
| **5** | Fill Realism Layer — SlippageModel, FillModel, LatencyModel, ExecutionSimulator; asymmetric SL/TP slippage; gap-through; partial fill; seeded deterministic randomness |
| **6** | Causal Reconstruction Layer — 4-domain attribution (Prediction, Execution, Exit, Friction); counterfactual metrics (perfect entry, zero slippage, ideal exit); MAE/MFE time-normalized; archetype drift tracking; deterministic replay audit |

### Pre-existing Tiers (1–7)

| Tier | Capability |
|------|------------|
| **1** | Cross-asset feature isolation, regime sizing, circuit breaker, trade quality gates |
| **2** | Vol-z spread model, square-root impact, ExecutionBridge |
| **3A** | Extended history (2000+, Sharpe 6.26, 0% ruin) |
| **3B** | Lead-lag matrix (205 relationships, 8 live edges) |
| **3C** | Adaptive macro expert weight |
| **4** | Scale-out + trailing, probability-based SL/TP, shadow SL/TP analytics |
| **5** | Macro narrative governance (weekly LLM overlay) |
| **6** | Liquidity regime model (volume/Amihud proxy) |
| **7** | PSI drift monitoring (fixed-width bin distribution shift detection) |

Full detail: [docs/HARDENING_ROADMAP.md](docs/HARDENING_ROADMAP.md)

---

## 10. SURVIVAL SIMULATION

Multi-layer survival framework at `research/risk/` with execution physics, regime-aware bootstrap, and deleveraging feedback. Validated across 1000 correlated paths.

**Key results (CF=0.40, 3yr):** Full Governance Sharpe 5.29 (vs Naked 6.03), 0% ruin, worst DD 8.5%, P50x 1.87. Extended history (25y): Sharpe 6.26, 0% ruin.

Full detail: [docs/SURVIVAL_SIMULATION.md](docs/SURVIVAL_SIMULATION.md)

---

## 11. SYSTEM INVARIANTS

- No train/serve skew (FeatureContract enforced)
- No look-ahead in feature construction (macro data lagged to publication)
- Deterministic replay via simulation snapshot system
- Strict signal/execution separation
- Backtest/live parity (training labels = runtime multipliers)
- Hysteresis-gated state transitions (no rapid flipping)
- Position manager as pure state machine (no I/O)
- Worst-wins penalty aggregation
- Synthetic stress capped at 25% of original series length
- Multiplicative governance layering: each layer independently configurable and gated
- Frozen kernel alignment: training label geometry matches runtime initial barriers (no adaptive logic leaks)
- Execution fill determinism: same seed + same inputs → identical FillResult across runs
- Degradation-only fill realism: Phase 5 may only degrade outcomes, never improve them
- Observe-only attribution: Phase 6 analytics never mutate labels, kernel, or policies
- Frozen execution contract: PolicyDecision (Phase 4), FillResult (Phase 5), and AttributionRecord (Phase 6) form an immutable causal ledger — deterministic replay, counterfactual evaluation, no upstream mutation

---

## 12. INFRASTRUCTURE

- Stateless inference, stateful execution with crash-safe snapshots
- Local HTTP observability dashboard (React + Vite + Tailwind + react-query) — sortable tables, sticky anchor nav, real-time session clock, governance state visualization with animated status indicators
- In-memory TTL cache with per-endpoint expiry (5-30s), gzip compression
- Configurable refresh interval via `QUANTFORGE_REFRESH_INTERVAL`
- JSONL decision tracing

---

## 13. KNOWN CONSTRAINTS

- Paper trading only (no live capital)
- Data limited to Yahoo Finance + FRED
- EURUSD excluded (pending COT integration)
- ^DJI marginal contribution under watch (ΔSharpe −0.11)
- 19 unscreened pairs not yet evaluated

---

## 14. SYSTEM CLASSIFICATION

> Deterministic market interaction simulator with causally decomposed execution quality, governance-driven execution control, and stress-conditioned survival modeling.

Distinguished from backtesting frameworks by treating execution physics as the primary unit of analysis, governance as a primary system component, stress survival as the central validation criterion, and portfolio topology as a downstream allocation concern.

---

## 15. EXECUTION LEDGER MODEL

The system now operates on a **frozen execution ledger** composed of immutable artifacts forming a causal chain of market interaction:

| Artifact | Phase | Immutability |
|----------|-------|--------------|
| Initial Barrier Geometry | Phase 0 | Frozen at kernel compile |
| Archetype Context | Phase 3 | Deterministic from feature vector |
| Entry Decision State | Phase 1 | Idempotent entry_id |
| Reward Geometry | Phase 2 | Compiled from regime×archetype |
| Policy Decision Packet | Phase 4 | Frozen instruction |
| Fill Simulation Result | Phase 5 | Seeded deterministic |
| Trade Attribution Record | Phase 6 | Observe-only append |

These seven artifacts form a **deterministic replay chain**: same inputs + same seed → identical execution history. This enables counterfactual evaluation — what-if analysis on any single artifact without recomputing upstream layers.

---

## 16. SYSTEM TRANSFORMATION

QuantForge has transitioned from:

> Predictive trading system with analytics

to:

> Causally decomposed execution simulator with observability-first architecture

| Dimension | Before (Phases 0–2) | After (Phases 0–6) |
|-----------|--------------------|--------------------|
| Core abstraction | ML pipeline | Execution contract ledger |
| Model role | Decision authority | Signal generator |
| Execution truth | Position manager state | Frozen PolicyDecision → FillResult |
| Analytics | Performance metrics | Causal decomposition with counterfactuals |
| Attribution | PnL attribution | 4-domain (Prediction, Execution, Exit, Friction) |
| Reproducibility | Stochastic | Seeded deterministic across all layers |

---

## 17. SYSTEM MATURITY STATE

QuantForge is now in **observability-complete execution simulation** state. The architecture is structurally complete through Phase 6. Future work is no longer about structural expansion, but about:

- **Statistical governance** — edge discovery from the full attribution surface
- **Regime sensitivity analysis** — expectancy surfaces conditioned on market regime
- **Policy optimization** — tuning execution within existing contract boundaries (no kernel contamination)

The architecture is contract-frozen. All subsequent development operates within the existing causal isolation boundaries and respects the observe-only constraint on the signal kernel.

---

## 18. DISCLAIMER

Research system only. No live capital execution. Not financial advice. Historical simulation results are not indicative of future performance.
