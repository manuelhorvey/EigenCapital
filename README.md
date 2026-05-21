# QUANTFORGE — SYSTEM SPECIFICATION

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Status](https://img.shields.io/badge/status-research%20system%20%7C%20paper%20trading-green)
![WalkForward](https://img.shields.io/badge/walk--forward-30%20assets%20validated-success)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## TABLE OF CONTENTS

1. [System Overview](#1-system-overview)
2. [System Objective](#2-system-objective)
3. [Getting Started](#3-getting-started)
4. [Live Simulation Portfolio](#4-live-simulation-portfolio)
5. [Data Architecture](#5-data-architecture)
6. [Feature Engineering](#6-feature-engineering)
7. [Model Architecture](#7-model-architecture)
8. [Labeling & Signal Generation](#8-labeling--signal-generation)
9. [Validation Framework](#9-validation-framework)
10. [Execution System (Paper Trading Engine)](#10-execution-system-paper-trading-engine)
11. [Risk & Governance Layer](#11-risk--governance-layer)
12. [Survival Monte Carlo Simulation](#12-survival-monte-carlo-simulation)
13. [Shadow Analytics System](#13-shadow-analytics-system)
14. [System Architecture (Causal Execution Graph)](#14-system-architecture-causal-execution-graph)
15. [System Invariants](#15-system-invariants)
16. [Infrastructure Design](#16-infrastructure-design)
17. [Known Constraints](#17-known-constraints)
18. [Research Status](#18-research-status)
19. [System Classification](#19-system-classification)
20. [Disclaimer](#20-disclaimer)

---

## 1. SYSTEM OVERVIEW

QuantForge is a modular quantitative research and simulation system for **macro-driven systematic strategies across FX, commodities, and digital assets**.

It implements a full lifecycle pipeline:

* Feature engineering under strict schema contracts (FeatureContract)
* Walk-forward out-of-sample validation across 5-year rolling windows
* Multi-class XGBoost signal generation (BUY / HOLD / SELL)
* Triple-barrier and forward-return labeling
* Portfolio construction with volatility targeting
* Continuous paper trading simulation with mark-to-market PnL
* Multi-layer governance: drift detection, validity state machine, shadow analytics
* **Survival Monte Carlo simulation** with execution physics, regime-aware bootstrap, and deleveraging feedback
* SL/TP execution surface optimization via replay engine

The system is strictly designed for **research and simulation under realistic market constraints**.

---

## 2. SYSTEM OBJECTIVE

QuantForge evaluates whether **macro-conditioned statistical structure produces persistent predictive edge under non-stationary market regimes**.

Primary research constraints:

* Structural regime shifts
* Feature interference across heterogeneous assets
* Cross-asset correlation instability
* Temporal decay of predictive signals
* Execution friction (spreads, gaps, partial fills)
* Robustness under adversarial perturbation

All strategies must pass **walk-forward validation and governance gating** prior to inclusion in the simulation portfolio.

---

## 3. GETTING STARTED

### 3.1 Installation

```bash
git clone https://github.com/user/quantforge.git
cd quantforge

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

### 3.2 Environment Configuration

```env
FRED_API_KEY=your_key_here
PYTHONPATH=.
```

### 3.3 System Execution

Start full simulation system (builds dashboard, starts engine, serves UI):

```bash
./monitor_all
```

Or manually:

```bash
python paper_trading/monitor.py
```

Dashboard (React + TypeScript + Tailwind CSS):

```
http://localhost:5000
```

Rebuild dashboard after frontend changes:

```bash
(cd paper_trading/dashboard && yarn build)
```

Dev mode (port 3000, proxies /state.json to port 5000):

```bash
(cd paper_trading/dashboard && yarn dev)
```

### 3.4 Running Research Simulations

Survival Monte Carlo (v3 — full pipeline):

```bash
python research/risk/survival_sim.py --execution-physics --btc-execution --deleverage --regime-bootstrap --exposure-telemetry
```

SL/TP execution surface sweep:

```bash
python research/execution_surface/surface_sweep.py
```

### 3.5 Running Backtests

```bash
python equity/walk_forward_eurusd.py
python equity/walk_forward_nzdjpy.py
```

---

## 4. LIVE SIMULATION PORTFOLIO

The system maintains an 11-asset continuously evaluated simulation portfolio with **plateau-optimized SL/TP configurations** derived from execution surface analysis.

| Asset  | Ticker   | Label | Cluster         | Alloc | sl_mult | tp_mult | R:R   |
| ------ | -------- | ----- | --------------- | ----- | ------- | ------- | ----- |
| EURAUD | EURAUD=X | tb20  | eur_cross       | 20%   | 0.54    | 1.77    | 1:3.3 |
| GC     | GC=F     | fwd60 | real_asset      | 15%   | 0.51    | 2.67    | 1:5.2 |
| NZDJPY | NZDJPY=X | tb20  | carry_fx        | 13%   | 0.51    | 2.02    | 1:4.0 |
| CADJPY | CADJPY=X | tb20  | oil_carry       | 10%   | 0.52    | 1.65    | 1:3.2 |
| AUDJPY | AUDJPY=X | tb20  | carry_fx        | 7%    | 0.52    | 2.01    | 1:3.9 |
| USDCAD | USDCAD=X | tb20  | usd_macro       | 7%    | 0.52    | 1.90    | 1:3.7 |
| GBPJPY | GBPJPY=X | tb20  | carry_fx        | 6%    | 0.50    | 2.22    | 1:4.4 |
| BTC    | BTC-USD  | tb20  | momentum_crypto | 5%    | 0.58    | 1.51    | 1:2.6 |
| USDJPY | USDJPY=X | tb20  | usd_macro       | 5%    | 0.52    | 1.97    | 1:3.8 |
| USDCHF | USDCHF=X | tb20  | usd_macro       | 4%    | 0.52    | 2.04    | 1:3.9 |
| GBPUSD | GBPUSD=X | tb20  | usd_macro       | 4%    | 0.52    | 1.97    | 1:3.8 |

* **Cash buffer**: 4% retained as dynamic risk slack.
* **SL/TP values**: migrated to plateau-center configs from aggregate execution surface analysis. These are tighter than the original 1:2.5 defaults and maximize risk-adjusted return across sweep space.

Stop-loss = vol × sl_mult, take-profit = vol × tp_mult. Each asset's triple-barrier training labels in `features/registry.py` must match runtime multipliers — enforced by `PaperTradingEngine.initialize()` assertion.

---

## 5. DATA ARCHITECTURE

### 5.1 Data Sources

* Yahoo Finance (OHLCV) — primary market data
* FRED macroeconomic series (yields, spreads, inflation)
* COT (Commitments of Traders) positioning data
* Parquet-based deterministic cache layer

### 5.2 Data Layout

```
data/
├── raw/               # Raw downloaded OHLCV parquet
├── processed/         # Cleaned, aligned macro factors
├── live/              # Runtime state (state.json, trade journal, equity history)
├── sandbox/           # Research outputs (OOS predictions, SL/TP analysis, risk simulations)
├── shadow_*/          # Shadow analytics persistence
└── loaders/           # Data ingestion (macro, COT, downloads)
```

---

## 6. FEATURE ENGINEERING

### 6.1 Feature Contract System

All features are enforced via a **FeatureContract** to ensure deterministic train/serve parity:

* `features/contract.py` — `FeatureContract` dataclass (ticker, label_type, macro_filters, price windows)
* `features/registry.py` — Ordered registry mapping feature categories to compute functions
* `features/builder.py` — Orchestrates feature computation and triple-barrier label application

### 6.2 Feature Categories

| Module | Features |
|--------|----------|
| `base_features` | OHLCV returns, ranges, gaps |
| `trend_features` | ADX, slope, curvature, path efficiency |
| `volatility_features` | ATR, Parkinson, Yang-Zhang, rolling vol |
| `mean_reversion_features` | RSI, Bollinger z-score, mean reversion strength |
| `regime_features` | Volatility regime classification, trend/range/volatile probabilities |
| `structural_features` | Skew, kurtosis, tail ratio, serial correlation |
| `cross_asset_features` | Inter-asset correlations, relative strength |
| `interaction_features` | Regime contrast, EMA contrast, transition risk |
| `pair_specific` | FX carry, rate differentials |

### 6.3 Driver Atlas

Each asset is mapped to a **driver-specific feature subspace** to prevent cross-regime contamination:

| Asset Group | Primary Drivers |
|-------------|----------------|
| JPY crosses (NZDJPY, AUDJPY, GBPJPY) | VIX, yield spreads, JPY momentum |
| USD pairs (USDCAD, USDCHF, GBPUSD, USDJPY) | DXY, rate differential, VIX |
| EURAUD | Rate differential, DXY, VIX |
| CADJPY | Oil correlation, VIX, yield spreads |
| GC (Gold) | Real yields, breakevens, DXY |
| BTC | Momentum, spread vs SPY, VIX |

---

## 7. MODEL ARCHITECTURE

### 7.1 Core Model

* **XGBoost** multiclass classifier
* Outputs: BUY / HOLD / SELL
* Configuration:
  * 300 trees
  * max_depth = 2
  * learning_rate = 0.02
  * Early stopping with validation set

### 7.2 Additional Model Types

* `models/hybrid_ensemble.py` — Hybrid ensemble combining XGBoost with auxiliary models
* `models/macro_expert_head.py` — Macro-economic expert head module for regime-conditioned predictions
* `models/regime/` — Regime classification models
* `models/mean_reversion/` — Mean-reversion specific models

### 7.3 Strategy Interfaces

All model components implement abstract base classes via `shared/`:

* `shared/model.py` — `ModelInterface` (implemented by `XGBoostModel`)
* `shared/signal.py` — `SignalStrategy` (implemented by `FixedThresholdStrategy`)
* `shared/sizing.py` — `PositionSizingStrategy` (implemented by `VolTargetSizing`)
* `shared/pnl.py` — `PnLStrategy`
* `shared/features.py` — `FeaturePipeline`
* `shared/registry.py` — `StrategyRegistry` singleton provides per-asset instances

---

## 8. LABELING & SIGNAL GENERATION

### 8.1 Labeling Regimes

* **tb20**: Triple-barrier event labeling (20-bar horizon). Take-profit and stop-loss levels set per-asset via `ASSET_LABEL_PARAMS` in `features/registry.py`. The `pt_sl` array `[tp_mult, sl_mult]` must match runtime `tp_mult`/`sl_mult` from `configs/paper_trading.yaml`.
* **fwd60**: 60-day forward return classification with fixed threshold.

### 8.2 Signal Pipeline

1. Feature computation via `FeaturePipeline`
2. XGBoost inference → probability distribution (BUY / HOLD / SELL)
3. `FixedThresholdStrategy` converts probabilities to discrete signals
4. `VolTargetSizing` applies volatility-scaled position sizing (active for BTC)
5. `TradeDecision` encapsulates signal + sizing → `PositionIntent` for execution

---

## 9. VALIDATION FRAMEWORK

### 9.1 Walk-Forward Protocol

* 5-year training window
* 1-year out-of-sample window
* Rolling evaluation (2021–2026)
* Strict temporal isolation (no leakage)
* Retrain frequency: annual (configurable)

### 9.2 Evaluation Metrics

* Sharpe ratio (annualized)
* Maximum drawdown
* Directional accuracy
* Stability of positive return windows

### 9.3 Empirical Results (Walk-Forward)

| Asset  | Sharpe | Stability | Notes |
| ------ | ------ | --------- | --------------------------- |
| NZDJPY | 2.72   | 5/5       | Strongest carry structure   |
| AUDJPY | 2.62   | 5/5       | Screened, promoted to live  |
| EURAUD | 2.28   | 5/5       | Feature augmentation uplift |
| GBPJPY | 1.75   | 4/5       | Screened, promoted to live  |
| CADJPY | 1.70   | 4/5       | Regime-dependent uplift     |
| USDCHF | 1.64   | 4/5       | Screened, promoted to live  |
| USDCAD | 1.48   | 4/5       | Stable macro sensitivity    |
| USDJPY | 1.28   | 4/5       | Screened, promoted to live  |
| GBPUSD | 1.24   | 4/5       | Screened, promoted to live  |
| GC     | 1.06   | 4/5       | Macro persistence observed  |
| BTC    | 0.83   | 3/5       | Structurally unstable       |

### 9.4 Model Governance Pipeline

1. Sandbox retraining
2. Four-lens evaluation (model / signal / portfolio / shadow)
3. Walk-forward validation
4. MAS scoring (6-dimensional compression metric)
5. Adversarial regime stress testing (9 perturbation modes)
6. Promotion gate evaluation

**Outcome classes**: LIVE_CANDIDATE → PAPER_TRADING_ONLY → SHADOW_ONLY → REJECT

---

## 10. EXECUTION SYSTEM (PAPER TRADING ENGINE)

### 10.1 System Structure

* `PaperTradingEngine` — Top-level orchestrator, runs signal generation for all assets each tick
* `AssetEngine` — Per-asset execution engine, owns model, features, position manager, validity state
* `PositionManager` — Position lifecycle (open, close, SL/TP checks, PnL) — pure state machine
* `PaperBroker` — Simulated fills at Yahoo Finance prices with configurable slippage/fees

### 10.2 Core Abstractions

* `TradeDecision` — Model output intent (signal, confidence, position_size)
* `PositionIntent` — Execution representation (side, price, SL/TP, vol)
* Separation enforced between: signal generation, execution logic, accounting

### 10.3 Per-Asset Risk Multipliers

Stop-loss and take-profit distances are set per asset via `configs/paper_trading.yaml`:

```yaml
assets:
  BTC:
    sl_mult: 0.58    # stop = entry × (1 − vol × 0.58)
    tp_mult: 1.51    # take-profit = entry × (1 + vol × 1.51)
```

The `PositionIntent.from_price_and_vol()` factory computes SL/TP from current volatility.

### 10.4 Training Alignment Validation

On startup, `PaperTradingEngine.initialize()` asserts runtime multipliers match training labels in `ASSET_LABEL_PARAMS`. This prevents silent training/execution misalignment.

### 10.5 Key Configuration

| Key | Default | Description |
| --- | ------- | ----------- |
| `capital` | 100000 | Starting capital |
| `position_size` | 0.95 | Capital utilization cap |
| `rebalance` | daily | Rebalance frequency |
| `halt.drawdown` | -0.08 | Drawdown halt threshold |
| `halt.monthly_pf` | 0.70 | Monthly profit factor minimum |
| `halt.signal_drought` | 30 | Max days without signal |
| `halt.prob_drift` | 0.15 | Max confidence drift |
| `assets.<name>.allocation` | — | Portfolio weight |
| `assets.<name>.sl_mult` | 1.0 | Stop-loss vol multiplier |
| `assets.<name>.tp_mult` | 2.5 | Take-profit vol multiplier |

---

## 11. RISK & GOVERNANCE LAYER

### 11.1 Validity State Machine (Active)

Each asset runs an independent validity state machine in `monitoring/validity_state_machine.py`:

* **GREEN** → full exposure (1.0×)
* **YELLOW** → reduced exposure (0.5×)
* **RED** → halted (0.0× — no PnL accrual)

Transitions use **hysteresis bands**, **exponential inertia smoothing**, and a **regime persistence lock** to prevent rapid state flipping. Input signals:

* Drawdown vs threshold
* Monthly profit factor
* Signal drought (days since last signal)
* Confidence drift from expected baseline

**Exposure gating**: Each tick, `run_once()` calls `update_validity()` and sets `pos_mgr.exposure_multiplier` to the state machine's output. This directly scales all PnL calculations — GREEN=full, YELLOW=half, RED=flat.

### 11.2 Drift Monitoring (5D)

* Model drift (KL divergence)
* Signal flip rate
* PnL MAE
* Feature set Jaccard similarity
* Regime consistency score

### 11.3 Shadow Risk Engine

* `risk_governance.py` — Real-time risk evaluation (composite risk score, exposure multiplier)
* `shadow_actions.py` — Corrective action recommendations (PAUSE / REDUCE / MONITOR)
* Advisory layer — computed but not enforced (validity state machine is the enforcement layer)

---

## 12. SURVIVAL MONTE CARLO SIMULATION

A multi-layer survival simulation framework at `research/risk/` that evaluates portfolio robustness under extreme market conditions with progressively increasing realism.

### 12.1 Execution Physics (`execution_physics.py`)

Models market microstructure degradation:

* **Spread expansion**: Base spread widens proportionally to volatility z-score, capped at max bps
* **Gap risk**: Stop-loss gap-through increases with vol, adding nonlinear downside
* **Partial fills**: Fill probability decays with vol; unfilled orders truncate returns
* **Deleveraging feedback**: When portfolio drawdown exceeds threshold (−10%), exposure is linearly reduced (up to 50% max), then recovers at 0.5%/day when above threshold

**Per-asset execution configs**: BTC-specific parameters (wider spreads, larger gaps, lower fill rates) reflect crypto market microstructure vs FX majors.

### 12.2 Regime-Aware Bootstrap

**Tail-weighted regime classification** (`vol³ composite index`):

* COMPOSITE = weighted avg of each asset's rolling vol z-score
* Weight ∝ vol³ — high-vol assets (BTC) dominate crisis detection
* Thresholds: CALM (<1.0σ), ELEVATED (1.0–2.0σ), CRISIS (>2.0σ)

**Regime-conditioned block sampling**: During bootstrap, blocks are sampled such that the starting day's regime matches the current simulated regime state. This preserves volatility clustering, crisis persistence, and deleveraging feedback compounding.

### 12.3 Portfolio Variant System

| Variant | Description |
|---------|-------------|
| Full Portfolio | All 11 assets at current allocations |
| No BTC | Excludes BTC, renormalized |
| BTC Capped 5% | BTC constrained to 5% |
| BTC Regime-Gated | BTC only trades in favorable regimes |

### 12.4 Stress Scenarios

| Scenario | Description |
|----------|-------------|
| Crypto Bear 2022 | −0.45%/day for 12 months on BTC |
| Flash Crash | −30% single-day shock across all assets |
| Correlation Spike | 6-month period at 0.90 inter-asset correlation + 2× vol + amplified execution friction |

### 12.5 Marginal Contribution Analysis

Leave-one-out delta for each asset against the full portfolio:
* ΔSharpe, ΔAnn.Return%, ΔWorstDD%, ΔCVaR, ΔRuin probability
* Performance assessment: growth engine / stabilizer / contaminant

### 12.6 Exposure Telemetry

Tracks the deleveraging system's behavior across all paths:

* Exposure cone (percentiles of leverage over time)
* Deleveraging trigger rate and frequency
* Regime-bucketed average exposure (CALM vs ELEVATED vs CRISIS)
* Min exposure distribution (crisis severity)

### 12.7 Calibration Results (v3 Baseline)

| Metric | Full | No-BTC | BTC-5% |
|--------|------|--------|--------|
| Sharpe | 3.78 | 5.44 | 4.98 |
| Ann.Ret | +22.8% | +26.9% | +25.4% |
| Worst DD | 27.5% | 11.6% | 16.0% |
| Ruin | 0% | 0% | 0% |

**Key findings**:
* BTC is a structural contaminant (ΔSharpe −1.73, ΔWorstDD +29.47pp)
* EURAUD and NZDJPY are the strongest positive contributors
* Flash crash contained at 35.8% worst DD (no ruin)
* Deleveraging activates on ~15% of paths, barely triggered under regime bootstrap (portfolio genuinely robust)
* Regime detection: CALM=1241, ELEVATED=606, CRISIS=5 days in 1,852-day sample

### 12.8 SL/TP Execution Surface Optimization

The `research/execution_surface/` module runs OHLCV-driven replay simulation over SL/TP grids to find plateau-center configurations:

* `replay_engine.py` — OHLCV-driven trade lifecycle simulation
* `surface_sweep.py` — Sweeps SL/TP combinations across parameter space
* Aggregate report at `data/sandbox/sltp_analysis/aggregate_report.json`

---

## 13. SHADOW ANALYTICS SYSTEM

Parallel observability layer operating independently of execution:

* **Shadow trade replication**: Wrapper strategy runs alongside primary model
* **Drift attribution**: KL divergence, signal divergence, feature impact
* **Regime context analysis**: Market regime classification overlay
* **Shadow feedback**: Structured event logging (signal + drift + risk + action)
* **Shadow learning**: Longitudinal behavioral memory and drift trends

This subsystem is strictly **non-executional**.

---

## 14. SYSTEM ARCHITECTURE (CAUSAL EXECUTION GRAPH)

The system is implemented as a deterministic transformation pipeline:

```mermaid
graph TD

A[Market + Macro Data Ingestion] --> B[FeatureContract Validation]
B --> C[Driver Atlas Routing]

C --> D1[JPY Carry: NZDJPY / AUDJPY / GBPJPY]
C --> D2[USD Macro: USDCAD / USDCHF / GBPUSD / USDJPY]
C --> D3[Real Yield: GC=F]
C --> D4[Hybrid Momentum: BTC]
C --> D5[Rate Differential: EURAUD]
C --> D6[Oil-Correlation: CADJPY]

D1 & D2 & D3 & D4 & D5 & D6 --> E[Labeling Layer]

E --> F1[tb20: Triple Barrier]
E --> F2[fwd60: Forward Returns]

F1 & F2 --> G[XGBoost Model Layer]

G --> H[Regime Classifier Overlay]
G --> I[Signal Generator]

I --> J[Risk Engine]
H --> J

J --> K[Portfolio Construction Engine]

K --> L[PaperBroker Execution Layer]

L --> M[Validity State Machine]
L --> N[5D Drift Engine]
L --> O[Shadow Diagnostics]

M & N & O --> P[Observability Layer]

subgraph "Research (Offline)"
    R1[Execution Surface Sweep]
    R2[Survival Monte Carlo]
    R3[Regime Bootstrap]
    R1 & R2 & R3 --> R[Research / Risk]
end

R --> A
```

---

## 15. SYSTEM INVARIANTS

* No train/serve skew (FeatureContract enforced)
* Deterministic replay via state store
* Strict signal/execution separation
* Stateless inference layer
* Backtest/live parity enforcement (training labels = runtime multipliers)
* Hysteresis-gated state transitions (no rapid flipping)
* Position manager as pure state machine (no I/O)

---

## 16. INFRASTRUCTURE DESIGN

* Stateless model inference layer
* Stateful execution engine with crash-safe snapshots
* Schema-versioned persistence layer (StateStore, EngineSnapshot)
* Local HTTP observability dashboard with React frontend
* Cached market data subsystem (parquet + memory)
* Paper broker with simulated fills, slippage, and fees
* Real-time decision tracing (JSONL trace log)

---

## 17. KNOWN CONSTRAINTS

* Paper trading only (no live capital execution)
* Data limited to Yahoo Finance + FRED
* Weekend liquidity discontinuities
* EURUSD excluded (pending COT integration)
* Ensemble layer not yet activated in production loop
* BTC structurally unstable as portfolio asset (confirmed by marginal contribution analysis)
* Regime detection calibrated on 1,852-day sample (2019–2026); may not generalize to longer horizons
* CRISIS regime only 0.27% of sample — crisis dynamics rely on stress scenario injection

---

## 18. RESEARCH STATUS

* **11-asset live paper trading** active with plateau-optimized SL/TP
* **30+ assets** evaluated via walk-forward testing
* **EURAUD** classified as first LIVE_CANDIDATE
* **24 untested FX pairs** screened; top performers promoted to live portfolio
* **Survival Monte Carlo v3** operational: execution physics + regime bootstrap + deleveraging + telemetry
* **SL/TP execution surface** analyzed for all 11 portfolio assets; migrated to plateau-center configs
* **Full governance pipeline**: validity state machine, drift detection, shadow analytics
* **Shadow system** continuously accumulating behavioral dataset
* **245 tests** across 16 test files — zero regressions

---

## 19. SYSTEM CLASSIFICATION

> Macro-conditioned systematic trading research platform with full lifecycle governance, adversarial validation, survival Monte Carlo simulation, and execution simulation infrastructure.

Designed to evaluate persistence of macro-driven structure under regime stress, cross-asset generalization constraints, and realistic market microstructure friction.

---

## 20. DISCLAIMER

Research system only. No live capital execution. Not financial advice. Historical simulation results are not indicative of future performance.
