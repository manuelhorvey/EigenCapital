# QuantForge — System Overview

Architecture, component responsibilities, execution lifecycle, and persistence model for the QuantForge cross-sectional research and paper trading platform.

---

# System Philosophy

QuantForge is designed around a simple operational principle:

> robustness matters more than alpha complexity.

The system prioritizes:

* deterministic execution,
* replay-oriented persistence,
* walk-forward validation,
* train/serve symmetry,
* per-asset isolation,
* governance layering,
* and operational observability

over maximizing in-sample returns.

The repository intentionally treats trading infrastructure as a distributed state-management problem rather than purely a signal-generation problem.

---

# High-Level Architecture

```text
Research Universe (36 assets)
        ↓
Walk-Forward Validation (expanding window)
        ↓
Asset Selection (GREEN / YELLOW / RED)
        ↓
Per-Asset Training (XGBoost, per-asset depth)
        ↓
Live Inference
        ↓
Calibration (P1 — BinnedCalibrator, per-asset, config-gated)
        ↓
Governance Filters (11 layers + P2 Kelly sizing + P3 factor model)
        ↓
Decision Pipeline Stages (19 stages: first-cycle → bar-jump → calibrate → resolve → sell-only filter → spread → stability → hysteresis → kelly → profit lock → manage → route → poll)
        ↓
Portfolio Weight Rebalance (P0 — 4 strategies: equal, risk parity, HRP, factor-constrained)
        ↓
Position Sizing Guardrails (P2 Kelly multiplier → drawdown taper → caps → leverage budget)
        ↓
Execution & Positioning (MT5 or PaperBroker)
        ↓
Persistence & Replay (schema migration, DB_SCHEMA_VERSION=2.0.0)
        ↓
Monitoring & Attribution
```

---

# System Architecture

```text
┌─────────────────────────────────────────────────────────────────────┐
│                       RESEARCH / SCREENING                          │
│                                                                     │
│  36+ tickers                                                        │
│      ↓                                                              │
│  trade_analysis.py (walk-forward style)                             │
│      ↓                                                              │
│  walk_forward_backtest.py                                           │
│      ↓                                                              │
│  score_tickers.py                                                   │
│      ↓                                                              │
│  Promotion to dashboard                                             │
│                                                                     │
│  Output:                                                            │
│  - per-asset SL/TP/depth calibration                                │
│  - GREEN / YELLOW / RED states                                      │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    MODEL TRAINING                                   │
│                                                                     │
│  fetch_asset_data() + fetch_asset_ohlcv()                            │
│      ↓                                                              │
│  build_alpha_features() + generate_regime_features()                │
│      ↓                                                              │
│  triple_barrier_labels()                                            │
│      ↓                                                              │
│  binary reduction (drop HOLD)                                       │
│      ↓                                                              │
│  XGBoost binary:logistic (per-asset max_depth)                      │
│      ↓                                                              │
│  model persistence + PSI baseline + regime model training           │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    LIVE INFERENCE                                   │
│                                                                     │
│  Parallel asset execution                                           │
│  ThreadPoolExecutor(max_workers=8)                                  │
│                                                                     │
│  fetch_live()                                                       │
│      ↓                                                              │
│  build_features()                                                   │
│      ↓                                                              │
│  XGBoost inference                                                  │
│      ↓                                                              │
│  archetype classification                                           │
│      ↓                                                              │
│  EntryOptimizer                                                     │
│      ↓                                                              │
│  ExecutionPolicyLayer                                               │
│      ↓                                                              │
│  PositionManager                                                    │
│      ↓                                                              │
│  Position Sizing Guardrails (drawdown taper → equity cap →         │
│    risk cap → leverage budget → backstop)                          │
│      ↓                                                              │
│  EntryService (price deviation gate → submit to broker)            │
│      ↓                                                              │
│  PaperBroker / MT5Broker (MT5 gets independent sizing via          │
│    _compute_mt5_qty with own equity/drawdown)                      │
│                                                                     │
│  Async diagnostics run off-thread                                   │
│  via daemon consumer queue                                          │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    STATE PERSISTENCE                                │
│                                                                     │
│  SQLite WAL-mode persistence                                        │
│                                                                     │
│  - trades                                                           │
│  - attribution                                                      │
│  - shadow_trades                                                    │
│  - confidence_buckets                                               │
│  - equity_history                                                   │
│                                                                     │
│  Replay-oriented append semantics                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

# Core Architectural Properties

| Property                    | Description                                                    |
| --------------------------- | -------------------------------------------------------------- |
| Walk-forward validated      | Assets must pass expanding-window validation before deployment |
| Per-asset isolation         | Every asset runs independently with its own model lifecycle    |
| Replay-oriented persistence | Persistent state supports deterministic reconstruction         |
| Immutable execution chain   | PolicyDecision → FillResult → AttributionRecord                |
| Governance-first execution  | Exposure controlled by layered governance                      |
| Failure isolation           | Asset failures cannot halt the global engine                   |
| Single entry authority      | All entries route through `_can_enter()`                       |
| Train/serve symmetry        | Shared feature generation between training and inference       |
| Parallel orchestration      | Assets execute concurrently through isolated actors            |
| Per-asset model depth       | `max_depth` configured per-asset (2–5), not global             |

---

# Execution Lifecycle

## 1. Research & Asset Selection

The offline research stage evaluates a universe of 36+ assets using expanding-window walk-forward validation.

### Validation Structure

* 3-year rolling training window
* 1-year forward evaluation (or 5-year full validation)
* per-asset SL/TP/depth calibration
* IC + hit-rate scoring
* directional consistency weighting

Assets are classified into GREEN / YELLOW / RED. Only promoted assets enter the live portfolio.

---

## 2. Model Training

Each promoted asset trains an independent XGBoost model.

### Training Pipeline

```text
fetch_asset_data()
        ↓
build_features() (per-asset from FEATURE_REGISTRY)
        ↓
triple_barrier_labels()
        ↓
drop HOLD states
        ↓
binary reduction {0,1}
        ↓
XGBoost binary:logistic
        ↓
persist model + PSI baseline
```

### Model Configuration

| Parameter     | Value             |
| ------------- | ----------------- |
| Objective     | `binary:logistic` |
| Trees         | 300               |
| Max Depth     | per-asset (2–5)   |
| Learning Rate | 0.02              |
| Scale Pos Weight | Imbalance ratio (n_neg/n_pos) |

Per-asset max_depth from `configs/paper_trading.yaml`. Regime model: 200 trees, LR=0.03, depth=2 (not loaded in production — ensemble disabled). No shared multi-asset model exists.

---

# Live Inference Pipeline

The live engine executes every 300 seconds.

## Runtime Pipeline

```text
 1. Fetch 5y OHLCV (MT5 or yfinance)
 2. Normalize timestamps (UTC TZ-naive)
 3. Refresh latest price (MT5 or 5d fallback)
 4. Build alpha features (9 per-asset + 4 cross-asset)
 5. Generate regime features from OHLCV (7 cols)
 6. Compute archetype features (ema_spread, adx, rsi, bb_zscore)
 7. PSI drift check (rolling 21d vs baseline, skipped first cycle)
  8. Validate inference truncation
  9. Run XGBoost inference → 3-col proba expansion
 10. **Calibrate probabilities** — apply per-asset `BinnedCalibrator` (P1; config-gated via `calibration.enabled`, default `true`). Reduces ECE from 0.36→0.02.
 11. Regime ensemble blend skipped (disabled portfolio-wide; base_weight=1.0)
 12. Meta-label inference (optional, XGBoost)
 13. FixedThresholdStrategy(0.45) → BUY/SELL/FLAT
 14. Archetype classification → TradeDecision
 15. Refresh MT5 spread for spread gate
 16. Decision pipeline stages (20 stages, `DEFAULT_STAGES`):
     a. First-cycle suppression — suppress trading on cold-start cycle 1
     b. Bar-jump suppression — suppress 60min if bar count changed >100
     c. Store prediction metadata — record pre-decision signal state
     d. Update MAE/MFE — update max adverse/favorable excursion
     e. Resolve signal — map proba to BUY/SELL/FLAT via FixedThresholdStrategy(0.45)
     f. Risk-off suppression — flat AUDUSD when VIX>0 & SPX<0 (AUDCHF removed)
     g. Sell-only filter — override BUY→FLAT for 8 inverted-BUY assets
     h. Spread gate — block entry if spread > per-class threshold (observe 720 cycles)
     i. Confidence gate — abort if net confidence below threshold
     j. Signal stability filter — require >0.65 max(prob_long, prob_short)
     k. Signal hysteresis — 2-of-3 agreement before flip
     l. Meta-label advisory — record meta-label recommendation (no enforcement)
     m. Update regime bar counter — track bars since last regime shift
     n. Conviction gate — flip gate based on regime conviction
     o. **Kelly sizing (P2)** — scale position by Kelly criterion (config-gated via `kelly.enabled`, default `false`)
     p. Profit lock gate — block flip if unrealized PnL > threshold
     q. Manage position — close/re-open with entry gate check
     r. Build entry artifacts — construct TradeDecision for execution
     s. Route execution policy — direct to PaperBroker or MT5Broker
     t. Poll deferred entries — execute pending deferred orders
  17. Route through governance (11 layers + P3 factor model monitoring + HealthMonitor + VaR/CVaR + sizing guardrails)
  18. Entry price deviation gate (skip if price drifted > max_entry_slippage_pct)
  19. Position sizing chain (P2 Kelly multiplier → drawdown taper → position cap → risk cap → leverage budget → backstop)
  20. Independent MT5 sizing (same chain with real broker equity)
  21. Execute position lifecycle (open/close/flip/trailing)
```

---

# Governance Architecture

QuantForge uses independently configurable governance layers with worst-wins aggregation, plus decision pipeline suppression stages, position sizing guardrails, and HealthMonitor circuit breaker.

## Governance Layers (11 + HealthMonitor)

| Layer                  | Scope      | Effect                    |
| ---------------------- | ---------- | ------------------------- |
| Validity state machine | Per asset  | Exposure 0–100%           |
| Feature stability      | Per asset  | Validity penalties        |
| Meta-labeling (XGBoost)| Per signal | Size scalar [0–1]         |
| Macro narrative        | Global     | SL +10%, size −20%        |
| Liquidity regime       | Per asset  | THIN: soft adjust, STRESSED: halt |
| PSI drift              | Per asset  | Penalties + halt at 3+ SEVERE |
| Sell-only filter       | Per asset  | Override BUY→FLAT for 8 inverted-BUY assets |
| Calibration (P1)       | Per asset  | Remap raw p_long via BinnedCalibrator (config-gated, enabled) |
| Kelly sizing (P2)      | Per asset  | Scale position by Kelly criterion (config-gated, disabled) |
| Factor model (P3)      | Portfolio  | Factor exposure monitoring via 9 groups (monitoring only) |
| Equity cluster alarm   | Global     | Flags ES/NQ/^DJI all same side (recommendation) |
| Circuit breaker        | Portfolio  | Multi-condition: dd, vol spike, halt ratio, consecutive losses (threshold=7) |
| Portfolio drawdown     | Global     | Circuit breaker at −15%   |
| Entry price deviation  | Per entry  | Skip if price drifted >2% |
| Profit lock            | Per flip   | Block flip if PnL >15%    |

**Live VaR/CVaR:** Rolling 60-period portfolio returns → VaR(95) = 5th percentile, CVaR = mean of tail. Computed in Phase 3g.

**RecoveryScheduler:** Exponential-backoff probe of halted actors in Phase 3g (`is_due()`/`record_result()`).

**Schema migration:** SQLite at `DB_SCHEMA_VERSION = "2.0.0"`. Auto-migrates at connect time — adds `cycle_id`, `vol_spike`, `var_95`, indexes.

## Decision Pipeline Stages

| Stage | Effect |
|-------|--------|
| First-cycle suppression | Suppress trading on cold-start cycle 1 |
| Bar-jump suppression | Suppress 60min if bar count changed >100 |
| Store prediction metadata | Record pre-decision signal state |
| Update MAE/MFE | Update max adverse/favorable excursion |
| Resolve signal | Map proba to BUY/SELL/FLAT |
| Risk-off suppression | Flat AUDUSD when VIX>0 & SPX<0 |
| Sell-only filter | Override BUY→FLAT for 8 inverted-BUY assets |
| Kelly sizing (P2) | Scale position by Kelly criterion (config-gated, disabled by default) |
| Spread gate | Block entry if spread > per-class threshold (observe 720 cycles) |
| Confidence gate | Abort if net confidence below threshold |
| Signal stability filter | Require >0.65 max(prob_long, prob_short) |
| Signal hysteresis | 2-of-3 agreement before flip |
| Meta-label advisory | Record meta-label recommendation (no enforcement) |
| Update regime bar counter | Track bars since last regime shift |
| Conviction gate | Flip gate based on regime conviction |
| Profit lock gate | Block flip if unrealized PnL > threshold |
| Manage position | Close/re-open with entry gate check |
| Build entry artifacts | Construct TradeDecision for execution |
| Route execution policy | Direct to PaperBroker or MT5Broker |
| Poll deferred entries | Execute pending deferred orders |

## Position Sizing Guardrails

Applied multiplicatively in `EntryService._submit_to_broker()`:

| Guardrail | Effect | Config |
|-----------|--------|--------|
| Drawdown taper | Linear 1.0→min between start_dd/end_dd | `size_taper_start_dd`, `size_taper_end_dd`, `size_taper_min` |
| Per-position cap | Clip to `max_position_pct_of_equity` of equity | `max_position_pct_of_equity` |
| Risk-per-trade cap | Clip or skip if SL risk exceeds `max_risk_per_trade_pct` | `max_risk_per_trade_pct`, `min_viable_position_pct` |
| Leverage budget | Atomic lock from `max_leverage × equity` pool | `portfolio_max_leverage` |
| Backstop multiplier | Ratchet-down on breach, 0.9 decay/cycle | (fixed) |

MT5 sizing runs the same chain independently using real broker equity (via `_compute_mt5_qty()`), excluding the leverage budget.

---

# Persistence Model

Persistent state is stored in SQLite WAL mode.

## Persistent Tables

| Table                | Purpose               |
| -------------------- | --------------------- |
| `trades`             | Trade records         |
| `attribution`        | Attribution outputs   |
| `shadow_trades`      | Counterfactual replay |
| `confidence_buckets` | Confidence analytics  |
| `equity_history`     | Equity curve history  |

---

# Portfolio Maturity Framework (P0–P4)

The system implements a 4-layer portfolio maturity framework. All layers are
config-gated and independently enablable.

## P0 — Portfolio Truth Layer (enabled: `factor_constrained_v1`)

**File:** `shared/portfolio_weights.py`

Pure function weight computation. 4 registered strategies:

| Method | Strategy |
|--------|----------|
| `equal_v1` | Simple 1/N allocation |
| `risk_parity_v1` | Equal risk contribution via scipy SLSQP |
| `hrp_v1` | Lopez de Prado HRP with `optimal_leaf_ordering` |
| `factor_constrained_v1` | Risk parity with factor exposure penalty (default) |

**Integration:** `engine_rebalance_service.py` reads `portfolio.weight_method` from config, calls `compute_weights()`.

## P1 — Calibration Layer (enabled)

**Files:** `shared/calibration/` — `BinnedCalibrator`, `BetaCalibrator`, `CalibrationRegistry`, `ECETracker`

Raw XGBoost probabilities are binned-calibrated per asset. Applied in `pipeline.py` after `_run_inference()`, before the decision pipeline. ECE reduced from 0.36→0.02 (94.3% avg, 19/19 assets >80%).

**Config:** `calibration.enabled: true`, `calibration.method: binned`, `calibration.n_bins: 10`

## P2 — Fractional Kelly Sizing (disabled)

**File:** `shared/kelly.py`

Converts calibrated probability + TP/SL barriers → position size multiplier. Kelly multiplier flows through `_composite_size_scalar()` as an extra scalar before position caps.

**Config:** `kelly.enabled: false` (disabled pending live validation data)

## P3 — Factor Model (enabled for monitoring)

**File:** `shared/factor_model.py`

9 factor groups (USD, EUR, AUD, NZD, CHF, CAD, GBP, US_EQUITY, COMMODITY) covering all 19 assets. Factor exposures computed per-cycle in `engine_state_service.py`, exposed in `state.json`.

## P4 — HRP Fix (2026-06-24)

**File:** `portfolio/hrp_allocator.py`

`_get_quasi_diag()` uses `optimal_leaf_ordering` for deterministic dendrogram leaf order, fixing prior arbitrary weight volatility from near-singular correlation matrices.

---

# Failure Isolation

Each asset executes independently. Failures in data ingestion, inference, governance, diagnostics, or execution cannot halt the global engine. Emergency portfolio circuit breakers activate when halt ratios exceed configured thresholds.

---

# Component Responsibilities

## Feature Engineering (`features/`)

| Module                | Purpose                             |
| --------------------- | ----------------------------------- |
| `builder.py`          | Per-asset feature construction      |
| `registry.py`         | Feature contracts (36 tickers)      |
| `labels.py`           | Triple-barrier labeling             |
| `archetypes.py`       | Market structure classification     |
| `macro_narrative.py`  | Weekly macro narrative overlays     |
| `liquidity_regime.py` | Liquidity classification            |
| `contract.py`         | Feature contract dataclass          |
| `fxstreet_fetcher.py` | FXStreet → LLM narrative extraction |

---

## Shared Framework (`shared/`)

| Module | Role |
|--------|------|
| `portfolio_weights.py` | P0 — 4 weight strategies, decorator pattern, `compute_weights()` |
| `calibration/` | P1 — `BinnedCalibrator`, `CalibrationRegistry`, `ECETracker` |
| `kelly.py` | P2 — `compute_kelly_fraction`, `compute_kelly_multiplier` |
| `factor_model.py` | P3 — 9 factor groups, factor-constrained optimization |
| `sizing.py` | Deprecated — replaced by P0–P2 layers |

## Paper Trading Engine (`paper_trading/`)

| Component                | Role                        |
| ------------------------ | --------------------------- |
| `PaperTradingEngine`     | Top-level orchestrator      |
| `AssetEngine`            | Per-asset lifecycle, `_kelly_multiplier`, `_calibration_registry` |
| `AssetInferencePipeline` | Live inference + calibration (P1) |
| `AssetTrainingPipeline`  | Training pipeline           |
| `PortfolioBuilder`       | Asset registry construction |
| `DecisionPipeline`       | 20-stage decision pipeline with Kelly sizing |
| `EngineRebalanceService` | Live portfolio rebalance via `compute_weights()` (P0) |
| `StateStore`             | SQLite persistence          |
| `EntryOptimizer`         | Entry conditioning          |
| `ExecutionPolicyLayer`   | Unified execution routing   |
| `PositionManager`        | Position lifecycle          |
| `PaperBroker`            | Simulated fills             |
| `ExecutionBridge`        | Slippage + impact           |
| `ShadowSLTPEngine`       | Counterfactual replay       |
| `DynamicSLTPEngine`      | Live trailing SL/TP         |
| `ScaleOutEngine`         | Partial profit-taking tiers |
| `AttributionCollector`   | Attribution pipeline        |
| `EngineOrchestrator`     | Parallel orchestration      |
| `AssetActor`             | Asset execution wrapper     |
| `HealthMonitor`          | Portfolio-level health      |
| `EntryService`           | Entry validation + RR check + Kelly sizing chain |
| `MetricsService`         | Dashboard metrics           |
| `GovernanceService`      | Governance state aggregation|
| `PositionService`        | Position lifecycle          |
| `StateStore`             | SQLite WAL persistence      |
| `WALRunner`              | Deterministic replay engine |

---

# Configuration

`configs/paper_trading.yaml` controls:
* capital allocation,
* rebalance frequency,
* per-asset SL/TP/depth,
* governance layers,
* orchestrator settings,
* narrative overlays,
* and liquidity controls.

---

# Data Persistence

| Store                 | Format     | Purpose                    |
| --------------------- | ---------- | -------------------------- |
| `state.json`          | JSON       | Dashboard snapshot         |
| `state.db`            | SQLite WAL | Persistent execution state |
| `trade_outcomes.json` | JSON       | Cached aggregate analytics |

---

# Key Entry Points

| Action                    | Command                                       |
| ------------------------- | --------------------------------------------- |
| Start engine + dashboard  | `./monitor_all`                               |
| Run engine only           | `python -m paper_trading.ops.monitor`         |
| Retrain all assets        | `python scripts/retrain_all_fixed.py`         |
| Train regime models       | `python scripts/train_regime_models.py`       |
| Walk-forward backtest     | `python scripts/walk_forward_backtest.py`     |
| PnL backtest              | `python scripts/backtest_pnl.py --weight-method factor_constrained_v1` |
| Train calibration models  | `python scripts/train_calibration.py`         |
| Replay historical weights | `python scripts/replay_rebalance.py --verify` |
| Score tickers             | `python scripts/score_tickers.py`             |
| Generate promotion report | `python scripts/generate_promotion_report.py` |
| Daily monitoring          | `python scripts/monitor_paper_trading.py`     |
| Run microbenchmark        | `python benchmarks/microbenchmark.py`         |
| Run tests                 | `pytest tests/ -q --tb=short`                 |
| Lint                      | `ruff check . && ruff format .`               |

Dashboard URL: http://127.0.0.1:5000

---

# Known Constraints

* Paper trading only (MT5 Exness demo — no live capital)
* Ensemble disabled portfolio-wide (base_weight=1.0; ADR-026)
* Calibration (P1) enabled; factor_constrained_v1 (P0) enabled; Kelly (P2) disabled pending live data
* Some FX crosses may produce incomplete first-cycle bars
* Macro data sourced from Yahoo Finance (DXY, VIX, SPX, WTI, TNX)
* THIN liquidity regime is soft warning (SL/size adjust, no halt); only STRESSED halts
* Confidence drift halt requires 10+ signals for stable mean estimate

---

# Future Work

* Deterministic full-day replay reconstruction
* Event-sequence verification tooling
* Distributed multi-engine orchestration
* Extended execution quality analytics
* Portfolio-level regime optimization
* Broker abstraction layer
* Advanced replay visualization tooling
