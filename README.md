
# QuantForge

![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
![Status](https://img.shields.io/badge/status-active%20paper%20trading%20%7C%20research-blue)
![Assets](https://img.shields.io/badge/paper--trade%20assets-6-brightgreen)
![WalkForward](https://img.shields.io/badge/walk--forward-30%20assets%20validated-success)
![MAS](https://img.shields.io/badge/model%20acceptance%20score-15--phase%20stack-blueviolet)
![Status](https://img.shields.io/badge/evaluation%20layers-5%20(signal%20%7C%20forward%20%7C%20stress%20%7C%20evolution%20%7C%20adversarial)-orange)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

**QuantForge** is a modular quantitative research framework focused on **macro-conditioned trading systems** across equities, FX, metals, and crypto. It features a live 24/7 paper-trading engine with a web dashboard and a complete model governance stack spanning sandbox evaluation, regime adversarial testing, trajectory tracking, and a formal promotion gate — turning model selection from metric comparison into regime-conditioned behavioral manifold analysis.

**This is a research and paper-trading system — not a production trading bot.**

---

## Live Paper Trading

The paper-trading engine runs continuously with the following allocation across 6 assets and 5 distinct driver clusters:

| Asset   | Ticker      | Label | Cluster         | Alloc | Key Features |
|---------|-------------|-------|-----------------|-------|------|
| BTC     | `BTC-USD`   | tb20  | momentum_crypto | 20%   | rate_diff, 2y_yield_delta_63, vix_delta_5, dxy_mom_21, vix_ma21, btc_mom_{10/21/63}, btc_vs_spy_{21/63} |
| GC=F    | `GC=F`      | fwd60 | real_asset      | 20%   | real_yield_delta_63, breakeven_delta_63, dxy_mom_63, gc_mom_63 |
| EURAUD  | `EURAUD=X`  | tb20  | eur_cross       | 22%   | rate_diff, dxy_mom_21, vix_ma21, vix_delta_5, euraud_mom_{21/63} |
| NZDJPY  | `NZDJPY=X`  | tb20  | carry_fx        | 15%   | vix_ma21, vix_delta_5, us_jp_10y_spread, nzdjpy_mom_21 |
| CADJPY  | `CADJPY=X`  | tb20  | oil_carry       | 13%   | vix_ma21, ca_jp_spread_mom_21, us_jp_10y_spread, vix_delta_5, ca_jp_10y_spread, dxy_mom_21, cadjpy_mom_{10/21/63} |
| USDCAD  | `USDCAD=X`  | tb20  | usd_macro       | 10%   | rate_diff, dxy_mom_21, vix_ma21, vix_delta_5, usdcad_mom_{21/63} |

### Run

```bash
./monitor_all
```

**Dashboard**: <http://127.0.0.1:5000>

- Engine refresh: every 30 minutes
- UI refresh: every 30 seconds
- Yahoo Finance resilience: exponential backoff (5s/15s/45s) + parquet cache fallback

### Dashboard Features

- Portfolio summary (Total Value, Return, Unrealized P&L, Trade Count)
- Per-asset signal cards with confidence meters, position details, and P&L
- Session-scoped execution log (auto-cleaned on restart)
- Performance metrics (Profit Factor, Win Rate, Sharpe, Mean Confidence)
- Validity & Halt condition monitors
- Regime status and advisory bar
- Risk governance dashboard (`/risk.json`, `/risk/{asset}.json`)
- Shadow action intelligence (`/shadow-actions`, `/shadow-actions/{asset}.json`)

---

## Research Track

Primary validated assets across 6 asset classes using walk-forward validation. Two label architectures are deployed: **tb20** (triple-barrier, 20-bar timeout) for mean-reverting/short-term assets, and **fwd60** (60-day forward return) for macro-trend assets. See [ADR-015](docs/adr/ADR-015-asset-specific-label-horizons.md).

### Model Specifications

- **Type**: XGBoost multiclass classifier (BUY / NEUTRAL / SELL)
- **Parameters**: 300 trees, max depth 2, learning rate 0.02
- **Labeling**: Triple-barrier (pt_sl=2.0, vertical barrier=20 bars) for tb20 assets; 60-day forward return classification for fwd60 assets
- **Sizing**: Volatility-scaled positions
- **Validation**: Rolling walk-forward (5yr train / 1yr test / 1yr step)

### Walk-Forward Results — Portfolio Assets (5-Year Historical)

5-year walk-forward evaluation: for each year (2021–2025), train a fresh model on data strictly before Jan 1, test on the full calendar year. Mean annualized Sharpe across the 5 out-of-sample windows:

| Asset  | Label | Features | Avg Sharpe | Pos Windows | Avg DD  | Avg Acc |
|--------|-------|:--------:|:----------:|:-----------:|:-------:|:-------:|
| USDCAD | tb20  | 6        | **1.48**   | 4/5         | 0.016   | 0.5238  |
| NZDJPY | tb20  | 4        | **2.72**   | 5/5         | 0.021   | 0.4717  |
| GC=F   | fwd60 | 4        | **1.06**   | 4/5         | 0.024   | 0.4049  |
| EURAUD | tb20  | 4→6      | **0.57→2.28** | 4/5→**5/5** | 0.020→0.012 | 0.4816→0.4898 |
| BTC    | tb20  | 4→10     | **0.39→0.83** | 3/5        | 0.286→0.144 | 0.4550→0.4182 |
| CADJPY | fwd60→tb20 | 4→9  | **0.08→1.70** | 3/5→**4/5** | 0.026→0.011 | 0.3468→0.4876 |

Four assets (EURAUD, BTC, CADJPY, USDCAD) were augmented with additional macro and momentum features in May 2026. Arrowed values show baseline → augmented improvements. GC and NZDJPY were left unchanged (feature sets already optimal for their data-generating processes).

See [ADR-015](docs/adr/ADR-015-asset-specific-label-horizons.md) for label methodology and [ADR-016](docs/adr/ADR-016-gold-validation.md) for GC=F validation. See [ADR-017](docs/adr/ADR-017-inference-lookahead-investigation.md) for inference integrity.

---

## Advanced Architecture

### Research (Ensemble)

| Module                    | Description |
|--------------------------|-----------|
| HybridRegimeEnsemble | Global XGBoost backbone (depth=2, 100 trees) with regime-specific expert heads (TREND/RANGE/VOLATILE) and protected macro head (0.45 blend) |
| MacroExpertHead | Asset-specific XGBoost (depth=2) with protected weight 0.45 — prevents price features drowning macro signal |
| RegimeClassifier | TREND/RANGE/VOLATILE/NEUTRAL — operates as risk/participation controller |
| DriverAtlas | Asset-to-feature-cluster routing: carry_fx, yield_equity, momentum_crypto, positioning |
| ValidityStateMachine | GREEN/YELLOW/RED capital allocation with PSI-gated hysteresis |
| WalkForwardEngine | 5yr rolling train, 1yr OOS test, bootstrap p<0.05 deployment gate |

### FeatureContract System

The feature algebra is governed by a **3-template grammar** that covers 100% of deployed features. This eliminates train/serve skew by enforcing identical computation in both training and live inference:

| Component | Description |
|-----------|-------------|
| FeatureContract | Frozen dataclass — ticker, name, label type/params, macro filters, price momentum windows, vs-SPY windows. Runtime validators (`validate_dataframe`, `validate_model`) act as CI safety net |
| FEATURE_REGISTRY | Canonical dict mapping 6 tickers to their contracts — single source of truth for feature sets, label strategy, and model paths |
| Builder | `build_features()` — single generic pipeline: compute labels, align macro, compute template features, drop NaN. Called identically by training script and live engine |
| contract.features | Computed property — derives canonical column names from contract fields, eliminating hardcoded `*_FEATURES` constants and slug-based naming mismatches |
| model_path() | Returns `{name}_model.pkl` — fixes the old mismatch where training saved `{slug}_model.pkl` but engine expected `{name}_model.pkl` |

### Paper Trading (Deployed)

| Component                 | Description |
|---------------------------|-----------|
| FeatureContract / Registry / Builder | Canonical feature algebra — contract-driven feature computation, validation, and model path resolution |
| StateStore | Versioned persistence boundary — EngineSnapshot, corrupt-file recovery, file locking, cache management |
| StrategyRegistry | Per-asset strategy routing — model, signal, sizing, PnL, and feature pipeline interfaces with auto-register and validation |
| Shared Interfaces | `shared/model.py`, `shared/signal.py`, `shared/sizing.py`, `shared/pnl.py`, `shared/features.py` — ABCs + default implementations wrapping all critical computations |
| TradeDecision | Pure model intent dataclass — signal, confidence, provenance, no execution side-effects |
| PositionIntent / PositionManager | Extracted position lifecycle — open, close, SL/TP check, PnL accounting, deterministic replay |
| ValidityStateMachine | Per-asset GREEN/YELLOW/RED state with hysteresis, inertia smoothing, regime persistence lock |
| ExecutionState | Portfolio-level ACTIVE/PAUSED/HALTED — derived from halt conditions and validity exposure |
| AssetEngine | Per-asset XGBoost (depth=2, 300 trees, lr=0.02), contract-driven feature computation, tb20 or fwd60 label routing, strategy-registry-backed |
| PaperTradingEngine | Orchestrates 6 assets, volatility-scaled sizing, halt conditions, P&L tracking |
| PaperBroker(BrokerInterface) | Simulated broker — yfinance fills at market price, configurable slippage/fees |
| Dashboard (stdlib http.server) | Real-time web UI with portfolio summary, signal cards, session-scoped log, performance metrics |
| Wrappers | `paper_trading/wrappers.py` — shadow recomputation layer: pure-function delegators to shared interfaces, used for output-identity verification |
| Tracer | `paper_trading/tracer.py` — structured JSONL event tracing of every decision cycle + shadow comparison (signal, sizing, PnL) |
| Diagnostics | `paper_trading/diagnostics.py` — root-cause analysis layer: signal divergence classification, model distribution tracking, one-at-a-time feature impact scoring, volatility regime context, PnL decomposition |
| Shadow Memory | `paper_trading/shadow_memory.py` — persistent longitudinal store partitioned by asset+date (JSONL); immutable baseline with histogram-based model proba, signal mismatch, PnL error, and regime distributions |
| Drift Scoring | `paper_trading/drift_scoring.py` — 5-dimensional drift engine: model KL divergence, signal mismatch rate, PnL MAE, feature Jaccard stability, regime consistency; `get_shadow_intelligence()` produces per-asset drift report |
| Risk Governance | `paper_trading/risk_governance.py` — advisory risk layer: weighted composite score → LOW/MEDIUM/HIGH with risk flags, explanations, and non-binding recommended action |
| Shadow Actions | `paper_trading/shadow_actions.py` — non-binding execution advisor: action_type, exposure_adjustment, recommended_guardrails |
| Shadow Feedback | `paper_trading/shadow_feedback.py` — persistent behavioral dataset generator: append-only feedback events partitioned by asset+month |
| Shadow Analytics | `paper_trading/shadow_analytics.py` — offline aggregation: learning profiles, stability ranking, systemic pattern detection |
| Shadow Learning | `paper_trading/shadow_learning.py` — offline knowledge distillation: learning profiles, latent patterns, regime map, insights |

### Model Governance (Sandbox)

| Module | Description |
|--------|-------------|
| `backtests/sandbox_retrain.py` | Isolated training pipeline with frozen DataLock audit trail |
| `backtests/model_comparator.py` | 4-lens evaluation: model AUC/logloss, signal agreement/flip rate, portfolio PnL/drawdown, shadow entropy — all regime-stratified |
| `backtests/forward_test.py` | Walk-forward hold-out: trains fresh model on pre-cutoff data, computes forward Sharpe/hit rate/stability for baseline + candidate |
| `backtests/mas.py` | Model Acceptance Score: 6-dim weighted compression (model/signal/portfolio/shadow/forward/stress) with 4 hard gates |
| `backtests/model_evolution.py` | Temporal trajectory: append-only JSONL, MAS velocity, equilibrium bands, cross-asset convergence |
| `backtests/model_promotion_engine.py` | 4-condition admission gate (performance/stability/consistency/safety) producing structured LIVE_CANDIDATE/PAPER_ONLY/SHADOW_ONLY/REJECT decisions |
| `backtests/adversarial_manifold.py` | 9-regime perturbation engine across 4 axes (volatility, correlation, trend, noise); CMSS score + attractor drift + stability class |

---

## Key Findings

- Feature augmentation is asset-dependent: 4-feature models suffice for assets with strong data-generating processes (GC: real yield + breakeven; NZDJPY: VIX + 10y spread). Augmenting with additional orthogonal signals (VIX delta, DXY momentum, shorter/longer momentum windows) lifted EURAUD from 0.57→2.28, CADJPY from 0.08→1.70, and USDCAD from 1.48→2.86 avg Sharpe in 5-year walk-forward. GC and NZDJPY regressed under augmentation — when the base features already capture the regime, more features add noise.
- Asset-specific driver features are mandatory: generic macro features fail on 28/30 assets tested; pair-specific features (VIX + bilateral yield spread for NZDJPY) flipped 0/7 → 5/7 positive windows
- Genuine diversification across 6 driver clusters: 6-asset portfolio spans momentum_crypto, real_asset, eur_cross, carry_fx, oil_carry, and usd_macro with max |r| < 0.40
- Feature interference is a real failure mode: macro features drowned by 25 price features until protected weight architecture separated them
- Macro features describe environment, not price response: yield_slope and real_yield_10y removed from XLF model because they stayed bearish through 2023–2024 rally; 2y_yield_delta_63 (direction, not level) was the fix
- EURUSD blocked at daily frequency: 8 years walk-forward showed 1.65% CAGR; requires COT positioning data

---

## System Architecture

```mermaid
flowchart TD
    A1[yfinance OHLCV] --> F
    A2[FRED macro series] --> F
    A3[Parquet cache] --> F

    F[Driver atlas — asset-specific feature sets]
    F --> |carry_fx| N1[NZDJPY: VIX + bilateral yield spread]
    F --> |real_asset| N2[GC=F: real yield + breakeven + DXY]
    F --> |momentum_crypto| N3[BTC: rate diff + yield delta + VIX + DXY + mom_10/21/63 + vs_spy_21/63]
    F --> |eur_cross| N4[EURAUD: rate diff + DXY + VIX + delta + mom_21/63]
    F --> |oil_carry| N5[CADJPY: VIX + spread + us_jp/ca_jp spread + DXY + mom_10/21/63]
    F --> |usd_macro| N6[USDCAD: rate diff + DXY + VIX + delta + mom_21/63]

    N1 & N2 & N3 & N4 & N5 & N6 --> L{tb20 vs fwd60}
    L --> |tb20| TB[Triple barrier\npt_sl=2.0 · 20-bar timeout]
    L --> |fwd60| FW[60-day forward return\n±2% threshold]
    TB & FW --> M1[Regime classifier\nTREND/RANGE/VOLATILE/NEUTRAL]
    TB & FW --> M2[Bootstrap deployment gate\np<0.20 for fwd60 · p<0.10 for tb20]
    TB & FW --> M3[Walk-forward engine\n5yr train · 1yr test]
    M1 & M2 & M3 --> S[Signal generator\nprob threshold 0.45]
    S --> R[Risk engine\nvol-scaled sizing · halt conditions · prob_drift]
    R --> P1[BTC 20%\nhalt DD −15%]
    R --> P2[GC=F 20%\nhalt DD −8%]
    R --> P3[EURAUD 22%\nhalt DD −8%]
    R --> P4[NZDJPY 15%\nhalt DD −6%]
    R --> P5[CADJPY 13%\nhalt DD −8%]
    R --> P6[USDCAD 10%\nhalt DD −8%]
    P1 & P2 & P3 & P4 & P5 & P6 --> Mon[Monitoring\nvalidity state machine · drift · dashboard]
```

---

## Repository Structure

```text
QuantForge/
├── backtests/            # Sandbox model governance stack (Phases 11–14)
│   ├── sandbox_retrain.py        # Orchestrator: trains isolated models + runs full eval pipeline
│   ├── model_comparator.py       # 4-lens evaluation engine (model/signal/portfolio/shadow)
│   ├── forward_test.py           # Walk-forward hold-out (Sharpe, hit rate, drawdown, stability)
│   ├── mas.py                    # Model Acceptance Score — 6-dim weighted compression + hard gates
│   ├── model_evolution.py        # Trajectory tracking: velocity, equilibrium bands, convergence
│   ├── model_promotion_engine.py # 4-condition admission gate with structured failure modes
│   └── adversarial_manifold.py   # 9-regime perturbation engine + CMSS stability scoring
├── paper_trading/       # Live engine + stdlib HTTP dashboard
│   ├── serve.py         # stdlib HTTP server
│   ├── engine.py        # Paper trading engine
│   ├── state_store.py   # Versioned persistence boundary (EngineSnapshot, cache, journal)
│   ├── decision.py      # TradeDecision / PositionIntent pure dataclasses
│   ├── position_manager.py  # Position lifecycle (open, close, SL/TP, PnL)
│   ├── monitor.py       # Entry point (data → signal → trade loop)
│   ├── wrappers.py      # Shadow recomputation layer (pure-function delegators)
│   ├── tracer.py        # Structured JSONL event tracing + shadow comparison
│   ├── diagnostics.py   # Root-cause analysis: signal divergence, model dist, feature impact, regime, PnL decomp
│   ├── shadow_memory.py # Persistent longitudinal store, partitioned by asset+date, baseline builder
│   ├── drift_scoring.py # 5-dim drift engine: model KL, signal mismatch, PnL MAE, feature stability, regime consistency
│   ├── risk_governance.py   # Advisory risk layer: weighted composite score + non-binding recommendations
│   ├── shadow_actions.py    # Non-binding execution advisor: action_type, guardrails from drift+risk
│   ├── shadow_feedback.py   # Persistent behavioral dataset generator (append-only, partitioned by asset+month)
│   ├── shadow_analytics.py  # Offline aggregation: learning profiles, stability ranking, systemic pattern detection
│   ├── shadow_learning.py   # Offline knowledge distillation: learning profiles, latent patterns, regime map, insights
│   ├── frontend/        # Dashboard UI (index.html, script.js, style.css)
│   └── models/          # 6 serialised XGBoost model pickles
├── shared/              # Strategy interfaces and registry
│   ├── __init__.py
│   ├── registry.py      # StrategyRegistry singleton — per-asset routing, auto-register, validation
│   ├── model.py         # ModelInterface ABC + XGBoostModel wrapper
│   ├── signal.py        # SignalStrategy ABC + FixedThresholdStrategy
│   ├── sizing.py        # PositionSizingStrategy ABC + VolTargetSizing
│   ├── pnl.py           # PnLStrategy ABC + DefaultPnLStrategy
│   └── features.py      # FeaturePipeline ABC + DefaultFeaturePipeline
├── scripts/             # Training & validation runners
│   ├── walk_forward_all.py
│   ├── train_all_assets.py
│   ├── gc_walk_forward.py
│   └── ...
├── equity/              # Walk-forward research scripts
├── archive/             # Retired model source code
├── models/              # Research models
│   ├── regime/          # Regime classifier
│   ├── ensemble/        # Model router
│   ├── mean_reversion/  # RSI + Bollinger for RANGE
│   ├── trend/           # Trend-following models
│   ├── volatility/      # Volatility models
│   ├── macro_expert_head.py
│   └── hybrid_ensemble.py
├── features/            # FeatureContract system + feature engineering pipeline
│   ├── contract.py      # FeatureContract dataclass + runtime validators
│   ├── registry.py      # FEATURE_REGISTRY — canonical contracts for 6 portfolio assets
│   └── builder.py       # Generic builder — compute_macro_derived, build_features, compute_label, model_path
├── labels/              # Triple-barrier & meta-labeling
├── signals/             # Signal filtering, thresholding, generation, paper signal adapter
├── risk/                # Position sizing, drawdown controls, exposure limits
├── monitoring/          # Validity state machine, drift detection, dashboard backend, MLflow, weekly reports
├── data/
│   ├── loaders/         # yfinance, FRED, COT downloaders
│   ├── raw/             # Raw OHLCV parquet files
│   ├── processed/       # Feature-engineered datasets & walk-forward results
│   ├── live/            # Runtime engine state, equity history, logs, yfinance cache
│   └── weekly_pipeline.py
├── diagnostics/         # Model audits, sweeps, SHAP analysis, isolation tests
├── portfolio/           # HRP allocator, risk parity, correlation clusters
├── execution/           # Broker interface, order manager, portfolio sync, PaperBroker (simulated broker)
├── configs/             # YAML configs (paper trading, forex) + driver atlas
├── tests/               # Pytest test suite (148 tests, regression-verified across all 14 phases + feature augmentation)
├── docs/                # Project documentation, runbook, system overview
│   └── adr/             # Architecture Decision Records (ADR-000 through ADR-017)
├── adr/                 # Additional ADRs (ADR-011 known issues)
├── notebooks/           # (placeholder — no notebooks yet)
├── .github/
│   └── workflows/       # CI pipeline (py_compile lint + pytest)
├── quantforge/          # Package root (version, logging)
├── main.py              # Minimal entry point
├── monitor_all          # Launch script (paper trading)
├── Makefile             # Dev targets (install, test, lint, run, clean)
├── pyproject.toml       # Project metadata & deps
└── requirements.txt     # Pinned dependencies
```

---

## Documentation

Project documentation and architecture decisions live alongside the code:

| Path | Description |
|------|-------------|
| [`docs/`](docs/) | Project documentation — guides, references, deep-dives |
| [`docs/adr/`](docs/adr/) | Architecture Decision Records — key design decisions and their rationale (ADR-000 through ADR-017) |
| [`adr/`](adr/) | Supplementary ADRs — known issues and deferred decisions |

ADR entries follow the standard [Michael Nygard template](https://github.com/joelparkerhenderson/architecture-decision-record) and are numbered sequentially.

---

## Setup

```bash
git clone git@github.com:manuelhorvey/QuantForge.git
cd QuantForge

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest pytest-cov   # dev dependencies

export PYTHONPATH=$PYTHONPATH:.
```

---

## Quick Start

```bash
# Train models for all 6 portfolio assets (contract-driven pipeline)
python scripts/train_all_assets.py

# Run walk-forward validation
python scripts/walk_forward_all.py

# Run tests
make test

# Start live paper trading + dashboard
./monitor_all
```

---

## Refactoring Phases (Zero-Behavior-Drift)

The paper-trading engine has undergone a structural refactoring across 15 phases, each preserving byte-identical outputs:

| Phase | Description | Status |
|-------|-------------|--------|
| **1** | Tracer + shadow comparison + baseline snapshot + live contract + dependency guard | ✓ |
| **2** | Shared interfaces (model, signal, sizing, PnL, features) + AssetEngine migration | ✓ |
| **3** | Strategy registry with per-asset routing + research_mode flag | ✓ |
| **4** | Wrapper consolidation (delegate to shared interfaces) + PnL shadow + dead code removal | ✓ |
| **5** | Shadow diagnostics layer: signal divergence, model distribution, feature impact, regime context, PnL decomposition | ✓ |
| **6** | Persistent shadow memory (asset+date partitioned JSONL) + 5-dim drift scoring engine + baseline initialization | ✓ |
| **7** | Risk governance layer: weighted composite risk score, advisory exposure_multiplier, non-binding recommended action, `/risk.json` dashboard endpoints | ✓ |
| **8** | Shadow action layer: non-binding execution advisor with action_type (NONE/MONITOR/REDUCE/PAUSE), reason_codes, guardrails, `/shadow-actions` endpoints | ✓ |
| **9** | Shadow feedback loop: persistent behavioral dataset generator with derived metrics (agreement_score, instability_index, risk_alignment); offline analytics toolkit | ✓ |
| **10** | Shadow learning compilation: offline knowledge distillation — 5-dim learning profiles, latent pattern mining, regime behavior map, shadow insights | ✓ |
| **11** | **Sandbox retraining harness**: physically isolated model training + 4-lens evaluation engine (model/signal/portfolio/shadow comparison) with regime-stratified signal agreement and frozen DataLock audit trail | ✓ |
| **11.5** | **Walk-forward test + M_stress**: out-of-sample hold-out evaluation (Sharpe, hit rate, drawdown, stability); regime stress robustness sub-score calibrated to 0.5 at identity | ✓ |
| **12** | **Model evolution tracking**: per-asset trajectory JSONL with MAS velocity (Δ/retrain), acceleration, sub-axis drift, equilibrium band estimation, cross-asset convergence tracking | ✓ |
| **13** | **Model promotion protocol**: 4-condition multivariate admission gate (performance/stability/consistency/safety) producing structured decisions (LIVE_CANDIDATE/PAPER_TRADING_ONLY/SHADOW_ONLY/REJECT) with explicit failure modes | ✓ |
| **14** | **Cross-manifold adversarial testing**: 9-regime perturbation engine (volatility shock/compression, correlation break/inversion, trend flip/burst, noise inject/spike); CMSS stability score + attractor drift + stability class (ROBUST/MODERATE/BRITTLE) | ✓ |
| **15** | **Feature augmentation (May 2026)**: Extended BTC, CADJPY, EURAUD, USDCAD with VIX delta, DXY momentum, shorter/longer momentum windows, and additional macro filters. CADJPY switched from fwd60 to tb20 labels. 5-year walk-forward showed avg Sharpe improvements of +0.44 (BTC), +1.62 (CADJPY), +1.71 (EURAUD), +1.38 (USDCAD). GC and NZDJPY left unchanged. Result: first LIVE_CANDIDATE promotion (EURAUD). | ✓ |

### Pipeline

```
sandbox retrain
  → 4-lens comparison (model/signal/portfolio/shadow)
  → walk-forward test (6mo hold-out)
  → MAS (6-dim weighted compression: model/signal/portfolio/shadow/forward/stress)
  → adversarial manifold (9 regime perturbations → CMSS)
  → trajectory append (velocity + equilibrium bands)
  → promotion gate (4-condition admission) → structured decision
```

The live engine is **swap-ready but locked**. The sandbox is a proper **model selection energy landscape**: stable models sit in an equilibrium basin (~80 MAS), genuine structural improvements must climb past 88 with >0.6 stress robustness, and degraded models fall below 70. No single metric can force deployment — MAS is a manifold position, not a pass/fail score.

After May 2026 feature augmentation, the promotion gate produced its first `LIVE_CANDIDATE` (EURAUD: MAS=85.58, M_stress=0.63, 4/4 conditions met) and `PAPER_TRADING_ONLY` (CADJPY: MAS=85.22, 3/4 conditions, M_stress=0.59 — 0.0064 below deployment threshold).

## Roadmap

### Near Term

- EURAUD shadow live test (30-day) — first LIVE_CANDIDATE promotion
- Live broker integration (Alpaca / Interactive Brokers) — PaperBroker(BrokerInterface) contract exists
- Adversarial manifold expansion: bootstrap volatility shocks, permuted regime segments, synthetic spread widening
- Shadow intelligence dashboard integration — surface drift, CMSS, and MAS trajectory in web UI
- CADJPY re-evaluation — 0.0064 below M_stress threshold; monitor if next retrain cycle crosses 0.60
- AUDJPY re-evaluation post-November — model trained, deferred pending correlation analysis

### Medium Term

- Ensemble manifold synthesis — merge accepted models via regime-conditional weighting
- External regime validation sets — periodic "unknown regime injection" tests to prevent over-calibration
- EURUSD/GBPUSD with COT data pipeline

---

## Research backlog

Assets pending validation: ETH-USD (momentum_crypto cluster), XLU/XLRE (yield_equity cluster). AUDJPY (model trained, deferred post-November — r=0.87 with NZDJPY).

Blocked pending data acquisition: EURUSD, GBPUSD (need CFTC COT weekly positioning data).

---

## Limitations

- Paper trading only (no real capital at risk)
- Weekend data staleness for equities/FX
- No live broker execution — PaperBroker(BrokerInterface) provides the contract; Alpaca/IBKR stubs exist
- EURUSD and GBPUSD blocked — requires COT positioning data
- Model validity depends on PSI distribution stability
- Paper trading uses XGBoost per asset with 4–10 features (asset-dependent); research ensemble (`HybridRegimeEnsemble`) not yet deployed — registry is swap-ready but locked (a single `StrategyRegistry.register_model()` call would activate it)
- Yahoo Finance data can be rate-limited; engine mitigates with exponential backoff (5s/15s/45s) + parquet cache fallback

---

## Disclaimer

This project is for **research and educational purposes only**. It is not financial advice. Trading involves substantial risk of loss. Past performance does not guarantee future results.

---

## Author

**MktOwl**  
Focus: Macro-driven systematic trading • Walk-forward validation • Production-grade research engineering

---

**Contributions, issues, and suggestions are welcome.**
