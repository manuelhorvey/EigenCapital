# EigenCapital — System Overview

Architecture, component responsibilities, execution lifecycle, and persistence model for the EigenCapital cross-sectional research and paper trading platform.

> **See also:** [`docs/PRODUCTION_SYSTEM_SPEC_v1.md`](PRODUCTION_SYSTEM_SPEC_v1.md) for the production system specification — scope, constraints, P0–P4 framework, and the complete system contract. SYSTEM_OVERVIEW.md covers day-to-day architecture; PRODUCTION_SYSTEM_SPEC.md defines what the system IS.

---

# System Philosophy

EigenCapital is designed around a simple operational principle:

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

The engine runs a continuous 5-phase orchestrator cycle. Each tick (every ~60s) executes the following loop:

```
             ┌───────────────────────────────────────────┐
             │ PRE: PortfolioStateSnapshot               │
             │ RiskBudget + PerformanceState             │
             │ RiskEngineV2 adaptive budget              │
             └─────────────┬─────────────────────────────┘
                           │
             ┌─────────────▼─────────────────────────────┐
             │ Phase 1: REFRESH                          │
             │ Parallel actor refresh + signal gen       │
             │ ThreadPoolExecutor 8 workers              │
             └─────────────┬─────────────────────────────┘
                           │
             ┌─────────────▼─────────────────────────────┐
             │ Phase 1b: ADMIT                           │
             │ PEK collect intents → filter → rank       │
             │ Close over-budget positions               │
             └─────────────┬─────────────────────────────┘
                           │
             ┌─────────────▼─────────────────────────────┐
             │ Phase 2: VALIDITY                         │
             │ Parallel validity state updates           │
             └─────────────┬─────────────────────────────┘
                           │
             ┌─────────────▼─────────────────────────────┐
             │ Phase 3: PORTFOLIO HEALTH                 │
             └─────────────┬─────────────────────────────┘
                           │
                ┌──────────▼──────────┐
                │ Circuit Breaker?    │
                │ 7-consec-loss /     │
                │ -15% DD?            │
                └──────┬──────┬───────┘
                  yes  │      │  no
           ┌────────────┐      │
           │ Flatten    │      │
           │ positions  │      │
           │ Emergency  │      │
           │ halt via   │      │
           │ Recovery-  │      │
           │ Scheduler  │      │
           └────────────┘      │
                               ▼
                 ┌───────────────────────────────┐
                │ Factor Exposures              │
                │ 10 factor groups              │
                 └─────────────┬─────────────────┘
                               │
                 ┌─────────────▼─────────────────┐
                 │ VaR / CVaR                    │
                 │ Rolling 60-period             │
                 └─────────────┬─────────────────┘
                               │
                 ┌─────────────▼─────────────────┐
                 │ MT5 Orphan Recon              │
                 └─────────────┬─────────────────┘
                               │
           ┌───────────────────▼───────────────────┐
           │ Phase A: Drain cleanup queues         │
           │ Phase B: Stale ticket detection       │
           │ Phase C: Dry-run orphan report        │
           │ Phase D: Self-healing adoption        │
           └───────────────────┬───────────────────┘
                               │
                 ┌─────────────▼─────────────────┐
                 │ Position Concentration        │
                 │ Net-short skew threshold      │
                 └─────────────┬─────────────────┘
                               │
                 ┌─────────────▼─────────────────┐
                 │ Phase 4: PERSIST              │
                 │ Flush buffers → SQLite WAL    │
                 │ Record outcomes → PerfState   │
                 │ State snapshot → state.json   │
                 └─────────────┬─────────────────┘
                               │
                 ┌─────────────▼─────────────────┐
                 │ (next cycle)                  │
                 └───────────────────────────────┘
```

**Weekend branch:** When `is_market_closed()` returns true, `engine.py:362–375` checks for `weekend_eligible` assets. If any exist (e.g. BTCUSD with `crypto: [0,24]` session tier), a filtered cycle runs processing only those assets at 0.5× position multiplier. All other assets skip refresh and show stale data. If no eligible assets exist, the cycle returns `{}` (legacy skip behavior).

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
│  - strategy_metadata                                                │
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

Per-asset max_depth from per-asset YAML files in `configs/domains/assets/`. Regime model: 200 trees, LR=0.03, depth=2 (not loaded in production — ensemble disabled). No shared multi-asset model exists.

---

# Live Inference Pipeline

The live engine executes every ~60 seconds by default (configurable via `EIGENCAPITAL_REFRESH_INTERVAL` env var).

## Runtime Pipeline

```text
 1. Fetch 5y OHLCV (MT5 or yfinance)
 2. Normalize timestamps (UTC TZ-naive)
 3. Refresh latest price (MT5 or 5d fallback)
  4. Build alpha features (21 per-asset + cross-asset feature columns: 9 core per-asset + 6 trend-exhaustion + 2 COT + 4 cross-asset; includes core momenta, carry, trend-exhaustion, and RSI divergence when OHLCV available)
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
   16. Decision pipeline stages (22 stages, `DEFAULT_STAGES`):
      a. First-cycle suppression — suppress trading on cold-start cycle 1
      b. Bar-jump suppression — suppress 60min if bar count changed >100
      c. Store prediction metadata — record pre-decision signal state
      d. Update MAE/MFE — update max adverse/favorable excursion
      e. Resolve signal — map proba to BUY/SELL/FLAT via FixedThresholdStrategy(0.45)
      f. Risk-off suppression — flat AUDUSD when VIX>0 & SPX<0
       g. VIX gate — suppress CL=F when VIX > 30; fail-open if VIX data missing or stale (>5 days old). Currently dormant — CL=F not in portfolio (gate applies only to `VIX_GATE_ASSETS = {"CL"}`).
      h. Sell-only filter — override BUY→FLAT for 3 inverted-BUY assets
      i. Spread gate — block entry if spread > per-class threshold (observe 720 cycles)
      j. Session gate — block entry outside market session hours per asset-class tier
      k. ADX entry gate — skip if ADX < threshold (observe-only, disabled by default)
      l. Confidence gate — abort if net confidence below threshold
      m. Signal hysteresis — 2-of-3 agreement before flip
      n. Meta-label advisory — record meta-label recommendation (no enforcement)
      o. Update regime bar counter — track bars since last regime shift
      p. Conviction gate — flip gate based on regime conviction
      q. **Kelly sizing (P2)** — scale position by Kelly criterion (config-gated, disabled by default)
      r. Manage position — close/re-open with entry gate check (includes embedded profit lock)
      s. Build entry artifacts — construct TradeDecision for execution
      t. Route execution policy — direct to PaperBroker or MT5Broker
      u. Poll deferred entries — execute pending deferred orders
      v. Update prob history — record probability history for drift monitoring
   17. Route through governance (16 layers + PEK admission + P3 factor model monitoring + HealthMonitor + VaR/CVaR + sizing guardrails)
  18. Entry price deviation gate (skip if price drifted > max_entry_slippage_pct)
  19. Position sizing chain (drawdown taper → position cap → risk cap → min viable gate)
    → PEK budget enforcement (closes lowest-ranked positions if portfolio notional exceeds max)
  20. Independent MT5 sizing (same chain with real broker equity)
  21. Execute position lifecycle (open/close/flip/trailing)
```

---

# Governance Architecture

EigenCapital uses independently configurable governance layers with worst-wins aggregation, plus decision pipeline suppression stages, position sizing guardrails, PEK admission controller, and HealthMonitor circuit breaker.

## Governance Layers (17 core + 3 adaptive budget + HealthMonitor + PEK + decision pipeline + sizing guardrails)

| Layer                  | Scope      | Effect                    |
| ---------------------- | ---------- | ------------------------- |
| Validity state machine | Per asset  | Exposure 0–100%           |
| Feature stability      | Per asset  | Validity penalties        |
| Meta-labeling (XGBoost)| Per signal | Size scalar [0–1]         |
| Macro narrative        | Global     | SL +10%, size −20%        |
| Liquidity regime       | Per asset  | THIN: soft adjust, STRESSED: halt |
| PSI drift              | Per asset  | Penalties + halt at 3+ SEVERE |
| Sell-only filter       | Per asset  | Override BUY→FLAT for 3 inverted-BUY assets |
| Calibration (P1)       | Per asset  | Remap raw p_long via BinnedCalibrator (config-gated, enabled) |
| Kelly sizing (P2)      | Per asset  | Scale position by Kelly criterion (config-gated, disabled) |
| Factor model (P3)      | Portfolio  | Factor exposure monitoring via 10 groups (monitoring only) |
| Circuit breaker        | Portfolio  | Multi-condition: dd, vol spike, halt ratio, consecutive losses (threshold=7) |
| Portfolio drawdown     | Global     | Circuit breaker at −15%   |
| Entry price deviation  | Per entry  | Skip if price drifted >2% |
| Profit lock            | Per flip   | Block flip if PnL >15%    |
| Sell tripwire          | Per exit   | 20-trade window, 65% WARNING threshold |
| Position concentration | Portfolio  | Flags >75% net-short skew (recommendation) |
| Weekend trading governance | Per cycle | Filtered cycle for eligible assets; 0.5× allocation multiplier |

**Live VaR/CVaR:** Rolling 60-period portfolio returns → VaR(95) = 5th percentile, CVaR = mean of tail. Computed in Phase 3h.

**RecoveryScheduler:** Exponential-backoff probe of halted actors in Phase 3h (`is_due()`/`record_result()`).

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
| VIX gate | Suppress CL=F when VIX > 30; fail-open if VIX data missing or stale (>5 days old). Currently dormant — CL=F not in portfolio. |
| Sell-only filter | Override BUY→FLAT for 3 inverted-BUY assets |
| Spread gate | Block entry if spread > per-class threshold (observe 720 cycles) |
| Session gate | Block entry outside market session hours per asset-class tier |
| ADX entry gate | Block entry if ADX below threshold (observe-only, disabled by default) |
| Confidence gate | Abort if net confidence below threshold |
| Signal hysteresis | 2-of-3 agreement before flip |
| Meta-label advisory | Record meta-label recommendation (no enforcement) |
| Update regime bar counter | Track bars since last regime shift |
| Conviction gate | Flip gate based on regime conviction |
| Kelly sizing (P2) | Scale position by Kelly criterion (config-gated, disabled by default) |
| Manage position | Close/re-open with entry gate check (includes embedded profit lock — blocks flip if unrealized PnL > threshold) |
| Build entry artifacts | Construct TradeDecision for execution |
| Route execution policy | Direct to PaperBroker or MT5Broker |
| Poll deferred entries | Execute pending deferred orders |
| Update prob history | Record probability history for drift monitoring |

```
  SUPPRESS ── First-Cycle ──► Bar-Jump
                                 │
                                 ▼
  SIGNAL   ── Store Meta ──► Update MAE/MFE ──► Resolve ──► Risk-Off ──► Sell-Only
                                                 BUY/SELL     Suppress     Filter
                                 │
                                 ▼
  GATE     ── Spread ──► Session ──► ADX ──► Confidence
                             │
                             ▼
  POSITION ── Stability ──► Hysteresis ──► Meta-Label ──► Conviction ──► Kelly ──► Profit ──► Manage
              Filter         2-of-3         Advisory        Gate          Sizing    Lock      Position
                             │
                             ▼
  EXECUTE  ── Build Artifacts ──► Route Execution ──► Poll Deferred ──► Update Prob History
```

## Position Sizing Guardrails

Applied multiplicatively in `EntryService._submit_to_broker()`:

| Guardrail | Effect | Config |
|-----------|--------|--------|
| Drawdown taper | Linear 1.0→min between start_dd/end_dd | `size_taper_start_dd`, `size_taper_end_dd`, `size_taper_min` |
| Per-position cap | Clip to `max_position_pct_of_equity` of equity | `max_position_pct_of_equity` |
| Risk-per-trade cap | Clip or skip if SL risk exceeds `max_risk_per_trade_pct` | `max_risk_per_trade_pct`, `min_viable_position_pct` |
| PEK budget enforcement | Closes lowest-ranked positions if total notional exceeds `max_leverage × equity × tolerance` | (Phase 1b orchestrator-level) |

MT5 sizing runs the same chain independently using real broker equity (via `_compute_mt5_qty()`), excluding PEK budget enforcement.

```
  effective_cap = capital_base × min(mtm/init, 3.0)
         │
         ▼
  notional = effective_cap × size_scalar
         │
         ▼
  Per-Position Equity Cap (max_position_pct_of_equity)
         │
         ▼
  Risk-per-Trade Cap — skip if below min_viable
         │
         ▼
  ┌─ Notional within PEK budget? ─┐
  │  Yes ──────────► Paper Broker │
  │  No  ──► PEK Admission Review │
  │         close lowest-ranked   │
  │         positions             │
  └───────────────────────────────┘
         │
         ▼
  MT5 Broker (real account balance, independent sizing)
```

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
| `strategy_metadata`  | Per-asset training + fallback metadata |

---

# Portfolio Maturity Framework (P0–P4)

The system implements a 5-layer portfolio maturity framework (P0–P4). All layers are
config-gated and independently enablable.

## P0 — Portfolio Truth Layer (enabled: `factor_constrained_v2`)

**File:** `shared/portfolio_weights.py`

Pure function weight computation. 8 registered strategies:

| Method | Strategy |
|--------|----------|
| `equal_v1` | Simple 1/N allocation |
| `risk_parity_v1` | Equal risk contribution via scipy SLSQP |
| `risk_parity_v2` | Ledoit-Wolf shrinkage covariance |
| `risk_parity_v3` | EWMA span=60 covariance |
| `hrp_v1` | Lopez de Prado HRP with `optimal_leaf_ordering` |
| `factor_constrained_v1` | Risk parity with factor exposure penalty (legacy) |
| `factor_constrained_v2` | Risk parity with hard linear inequality constraints — binds CHF ≤0.20 (default) |
| `conviction_weighted_v1` | Risk parity tilted by model conviction scores |

**Integration:** `engine_rebalance_service.py` reads `portfolio.weight_method` from config, calls `compute_weights()`.

## P1 — Calibration Layer (enabled)

**Files:** `shared/calibration/` — `BinnedCalibrator`, `BetaCalibrator`, `CalibrationRegistry`, `ECETracker`

Raw XGBoost probabilities are binned-calibrated per asset. Applied in `pipeline.py` after `_run_inference()`, before the decision pipeline. ECE reduced from 0.36→0.02 (94.3% avg, 16/16 assets >80%).

**Config:** `calibration.enabled: true`, `calibration.method: binned`, `calibration.n_bins: 10`

## P2 — Fractional Kelly Sizing (disabled)

**File:** `shared/kelly.py`

Converts calibrated probability + TP/SL barriers → position size multiplier. Kelly multiplier flows through `_composite_size_scalar()` as an extra scalar before position caps.

**Config:** `kelly.enabled: false` (disabled pending live validation data)

## P3 — Factor Model (enabled for monitoring)

**File:** `shared/factor_model.py`

10 factor groups (USD, EUR, AUD, NZD, CHF, CAD, GBP, JPY, US_EQUITY, COMMODITY) covering all 22 assets. Factor exposures computed per-cycle in `engine_state_service.py`, exposed in `state.json`.

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
| `portfolio_weights.py` | P0 — 8 weight strategies, decorator pattern, `compute_weights()` |
| `calibration/` | P1 — `BinnedCalibrator`, `CalibrationRegistry`, `ECETracker` |
| `kelly.py` | P2 — `compute_kelly_fraction`, `compute_kelly_multiplier` |
| `factor_model.py` | P3 — 10 factor groups, factor-constrained optimization |
| `sizing.py` | Deprecated — replaced by P0–P2 layers |

## Paper Trading Engine (`paper_trading/`)

| Component                | Role                        |
| ------------------------ | --------------------------- |
| `PaperTradingEngine`     | Top-level orchestrator      |
| `AssetEngine`            | Per-asset lifecycle, `_kelly_multiplier`, `_calibration_registry` |
| `AssetInferencePipeline` | Live inference + calibration (P1) |
| `AssetTrainingPipeline`  | Training pipeline           |
| `PortfolioBuilder`       | Asset registry construction |
| `DecisionPipeline`       | 22-stage decision pipeline with Kelly sizing (config-gated)
| `EngineRebalanceService` | Live portfolio rebalance via `compute_weights()` (P0) |
| `StateStore`             | SQLite persistence facade (`paper_trading/state_store.py`) — delegates to `_DatabaseStore`, `_SnapshotManager`, `_AnalyticsStore`, `_DataCache` in `paper_trading/state/` |
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
| `ReplayRunner`           | Deterministic replay engine (`paper_trading/replay/runner.py`) |

---

# Configuration

The domain configuration tree in `configs/domains/` controls all system parameters:
* capital allocation (`configs/domains/risk/capital.yaml`),
* rebalance frequency,
* per-asset SL/TP/depth (`configs/domains/assets/<TICKER>.yaml`),
* governance layers (`configs/domains/governance/`),
* orchestrator settings,
* narrative overlays (`configs/domains/governance/narrative.yaml`),
* and liquidity controls (`configs/domains/governance/liquidity.yaml`).

All domain files are loaded by `PaperConfigRegistry` in `configs/paper_config_registry.py`.

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
| Retrain all assets        | `python scripts/training/retrain_all_fixed.py`         |
| Train regime models       | `python scripts/training/train_regime_models.py`       |
| Walk-forward backtest     | `python scripts/backtest/walk_forward_backtest.py`     |
| PnL backtest              | `python scripts/backtest/backtest_pnl.py --weight-method factor_constrained_v2` |
| Train calibration models  | `python scripts/training/train_calibration.py`         |
| Replay historical weights | `python scripts/replay/replay_rebalance.py --verify` |
| Walk-forward summary      | `python scripts/optimization/per_asset_quality.py`     |
| Daily monitoring          | `python scripts/ops/monitor_paper_trading.py`     |
| Run microbenchmark        | `python benchmarks/microbenchmark.py`         |
| Run tests                 | `pytest tests/ -q --tb=short`                 |
| Lint                      | `ruff check . && ruff format .`               |

Dashboard URL: http://127.0.0.1:5000

---

# Known Constraints

* Paper trading only (MT5 Exness demo — no live capital)
* Ensemble disabled portfolio-wide (base_weight=1.0; ADR-026)
* Calibration (P1) enabled; factor_constrained_v2 (P0) enabled with hard linear constraints; Kelly (P2) disabled pending live data
* Some FX crosses may produce incomplete first-cycle bars
* Macro data sourced from Yahoo Finance (DXY, VIX, SPX, WTI, TNX)
* THIN liquidity regime is soft warning (SL/size adjust, no halt); only STRESSED halts
* Confidence drift halt requires 10+ signals for stable mean estimate

---

# Document Metadata

**Last updated:** 2026-07-05

---

# Future Work

* Deterministic full-day replay reconstruction
* Event-sequence verification tooling
* Distributed multi-engine orchestration
* Extended execution quality analytics
* Portfolio-level regime optimization
* Broker abstraction layer
* Advanced replay visualization tooling
