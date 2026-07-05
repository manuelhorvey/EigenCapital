# EigenCapital — Glossary of Terms

> Reference document for domain-specific terminology used across the
> EigenCapital codebase and documentation. Entries are organized by
> category for quick lookup.

**Last updated:** 2026-07-05

---

## Table of Contents

- [Trading Concepts](#trading-concepts)
- [System Architecture](#system-architecture)
- [Engine & Orchestration](#engine--orchestration)
- [Governance & Risk](#governance--risk)
- [Portfolio Management](#portfolio-management)
- [Model Inference & Training](#model-inference--training)
- [Features & Labels](#features--labels)
- [Metrics & Statistics](#metrics--statistics)
- [Execution & Broker](#execution--broker)
- [Configuration & Infrastructure](#configuration--infrastructure)
- [Dashboard & UI](#dashboard--ui)
- [Acronyms Quick Reference](#acronyms-quick-reference)

---

## Trading Concepts

### R-Multiple (R)
The fundamental unit of trade outcome measurement, expressed as a multiple
of the initial risk (stop-loss distance). A trade that risks $100 and
returns $250 is +2.5R. All portfolio metrics (total_R, avg_R, max_dd_R)
use R-multiples to normalize across assets with different price scales.
R-multiples are additive across trades and dimensionless, enabling
cross-asset aggregation.

### Breakeven Win Rate (BE WR)
The win rate required for a trading system to break even given its
TP/SL ratio: `BE_WR = sl_mult / (tp_mult + sl_mult)`. A system with
tp=3, sl=1 requires a 25% win rate to break even. The BE WR is the
primary gauge of whether a model's actual win rate produces positive
expected value.

### TP/SL Ratio
The ratio of take-profit distance to stop-loss distance (tp_mult / sl_mult).
A ratio > 1.0 means TP is farther than SL (more reward per unit risk).
A ratio < 1.0 penalizes the model — it needs a higher win rate to be
profitable. After the June 2026 optimizer sweep, most assets target
ratio=3.0 with SL maintained above intraday noise via geometric mean
constraint.

### Walk-Forward Validation
A time-series cross-validation method that trains on expanding or
rolling windows and tests on out-of-sample (OOS) forward periods.
EigenCapital uses **expanding-window** walk-forward with CRIT-1 purging
(embargo between train/test) to prevent leakage. Each fold tests
on data strictly after the training window. Promoted assets must pass
walk-forward with positive total_R and Sharpe.

### Out-of-Sample (OOS)
Data not seen during model training, used for performance evaluation.
In walk-forward validation, each fold's test set is OOS relative to
that fold's training set. OOS metrics (total_R, Sharpe, max_dd) are
the basis for all promotion and diagnosis decisions.

### Expanding Window
A training design where each successive fold uses ALL prior data up to
the test window (never discards old data). Contrast with rolling window
(drops oldest data as new data arrives). Expanding window is the default
in EigenCapital; rolling window is proposed as an optional variant for
decay measurement.

### Rolling Window
A training design that uses a fixed-size trailing window of data
(e.g., 3 years), discarding older observations as new data arrives.
Not yet implemented in production — proposed for measuring model decay
independently of data volume.

### Purged Walk-Forward (PurgedWF)
A walk-forward variant with an embargo gap between training and test
sets to prevent leakage from overlapping labels. EigenCapital enforces
`gap >= vertical_barrier` — the gap is at least as large as the label
lookahead window.

### SELL_ONLY
A decision pipeline filter that overrides BUY signals to FLAT for
assets where the model's BUY prediction is inverted (p_long > 0.5
reliably predicts the wrong direction). Currently applied to 3 assets
(CADCHF, NZDCHF, EURAUD) after walk-forward counterfactual ablation
falsified all causal hypotheses (carry, DXY) for the BUY inversion.

### SELL_ONLY Filter Tripwire
A monitoring mechanism that tracks SELL-side win rate on SELL_ONLY
assets via a 20-trade sliding window. If SELL WR drops below 65%,
a WARNING is logged. Resets on recovery.

### Signal Hysteresis
A decision pipeline stage requiring 2-of-3 consecutive signals to
agree before a position flip is allowed (`HYSTERESIS_WINDOW=3`,
`HYSTERESIS_MIN_AGREE=2`). Prevents signal chatter from causing
frequent position flips.

### Profit Lock
A decision pipeline gate that blocks position flips when unrealized PnL
exceeds `profit_lock_threshold_pct` (default 15%). Protects profitable
positions from being closed by model signal instability.

### Bar-Jump Suppression
A first-cycle safety stage that suppresses all trading for 60 minutes
when the number of bars changes by >100 (indicating a data-source switch
from MT5 to yfinance or vice versa). Stage 0 in `DEFAULT_STAGES`.

### First-Cycle Suppression
Suppresses all trading on the first inference cycle after a cold
engine start. Mitigates the cold-start transient where regime features
calculated from 200 history rows differ from steady-state 1-row updates.
Cycles 2+ produce bit-for-bit identical outputs.

### Deferred Entry
An order that could not be executed immediately (e.g., price deviation
gate blocked it) and is persisted to be retried on subsequent cycles.
Deferred entries expire after `entry_defer_max_bars` (default 5). The
SELL_ONLY filter checks deferred entries to prevent bypass.

### Weekend-Eligible Asset
An asset configured with `weekend_eligible: true` that continues
inference and trading during market-closed periods (weekends, holidays).
Currently only BTCUSD with `crypto: [0,24]` session tier. Weekend trades
use a 0.5× allocation multiplier.

### Weekend Allocation Multiplier
A scalar (default 0.5) applied to position sizes for weekend-eligible
assets. Reduces exposure during lower-liquidity weekend conditions.

### Adaptive Exit Engine
A three-stage exit management system:
1. **Breakeven lock** (at `be_lock_r` MFE, default 0.5R): move SL to entry
2. **Retracement trail** (at `trail_activation_r` MFE, default 0.8R): set SL at `peak - retrace_pct × (peak - entry)`
3. **Time decay** (after `time_decay_start` candles): gradually tighten retracement tolerance
Validated to improve portfolio total_R from +519.5R to +3,209R (6.2×)
in walk-forward simulation.

### Scale-Out (Pyramiding Tiers)
Partial profit-taking at configurable levels. Tier profiles are generated
dynamically by the TP compiler based on archetype and convexity — typically
4 equal tiers (25% at 0.25× / 0.50× / 0.75× / 1.00× of original TP
multiplier). Stop-loss moves to breakeven after Tier 1 fills.

### Stacking (Pyramiding)
Adding incremental layers to existing winning positions. Currently
disabled by default after walk-forward analysis showed no portfolio
Sharpe benefit (increases notional concentration without commensurate
risk-adjusted return improvement).

### TP Compiler Convexity
The TP compiler applies a convexity multiplier to TP distance based on
archetype: MOMENTUM_IGNITION=6.0, BREAKOUT=5.0, etc. Capped at `MAX_RR=5.0`
to prevent unrealistically large TP distances.

---

## System Architecture

### EigenCapital
The project name (formerly Quorrin, renamed 2026-07-02). Cross-sectional
multi-asset research and paper trading platform with per-asset XGBoost
models, 15-layer governance, adaptive exits, and MT5 bridge execution.

### Paper Trading Engine
The top-level runtime orchestrator (`PaperTradingEngine`) that manages
the 5-phase cycle across all assets. Runs on simulated $100K capital
with independent sizing from MT5.

### AssetEngine
Per-asset lifecycle manager responsible for model loading, inference,
signal generation, and position lifecycle. Each asset has its own
`AssetEngine` instance running in the parallel orchestrator.

### EngineOrchestrator
The parallel execution engine (`EngineOrchestrator`) that coordinates
the 5-phase cycle using ThreadPoolExecutor (8 workers). Responsible
for signal generation (Phase 1a), PEK admission (Phase 1b), validity
updates (Phase 2), portfolio health (Phase 3), and persistence (Phase 4).

### EnginePhase
An `IntEnum` defining orchestrator phases: PRE, REFRESH, ADMIT,
VALIDITY, HEALTH, PERSIST. Each phase maps to a specific set of
operations in the 5-phase cycle.

### AssetActor
An execution wrapper around `AssetEngine` that manages an asset's
lifecycle within the parallel orchestrator. Each actor is isolated —
failures cannot halt the global engine.

### Config Registry
`PaperConfigRegistry` (in `configs/paper_config_registry.py`) is the
typed configuration loader that reads YAML files from the domain tree
(`configs/domains/`) and composes them into a unified `EngineConfig`.
The legacy monolithic `configs/paper_trading.yaml` was deleted in
Phase 12.7.

### Domain Tree
The directory structure under `configs/domains/` that organizes
configuration by domain concern: risk (capital, halt, sizing, exits),
portfolio (weights, factor model), ML (calibration, ensemble, meta_labeling,
triple_barrier), broker (MT5), execution (spreads, sessions), governance
(regime_geometry, liquidity, narrative), infrastructure (alerts),
assets (per-asset YAML files), and modes (production, challenge, live).

### LIVE_CONTRACT.md
The immutable system contract file that documents exact behavior of
the production paper trading system. Any deviation from this contract
is a trading bug. Changes require full regression validation.

### AGENTS.md
Day-to-day operational guide for the EigenCapital system. Contains
architecture quick-reference, common tasks, known issues, and the
complete historical timeline of fixes and discoveries.

### Phase 12 (Configuration Migration)
The project phase that migrated from a single monolithic
`configs/paper_trading.yaml` to a domain-separated config tree.
Completed 2026-07-05. All config editing now goes through per-domain
files in `configs/domains/`.

---

## Engine & Orchestration

### 5-Phase Cycle
The orchestrator's main loop executed every ~30s:
1. **PRE** — Build `PortfolioStateSnapshot`, `RiskBudget`, `PerformanceState`
2. **Phase 1a (REFRESH)** — Parallel actor refresh and signal generation (8 threads)
3. **Phase 1b (ADMIT)** — PEK collects intents → filter → rank → enforce budget
4. **Phase 2 (VALIDITY)** — Parallel validity state machine updates
5. **Phase 3 (HEALTH)** — Portfolio health: VaR/CVaR, MT5 orphan recon, position concentration, circuit breaker
6. **Phase 4 (PERSIST)** — Flush WAL buffers → SQLite → record outcomes → state.json

With MT5 orphan sub-phases (A: drain cleanup, B: stale ticket detection,
C: dry-run orphan report, D: self-healing adoption).

### Portfolio Execution Kernel (PEK)
The central portfolio admission and risk budgeting system comprising:
- `PortfolioStateSnapshot` — immutable single source of truth for portfolio exposure
- `RiskEngineV2` — adaptive risk budget scaling with drawdown/performance
- `PerformanceState` — outcome tracker + velocity processor → anticipatory scalar [0.5, 1.5]
- `PortfolioAdmissionController` — two-stage filter → rank → enforce budget

### PortfolioAdmissionController
The PEK admission component that collects trade intents from all assets,
applies hard filters, ranks survivors by composite score, allocates
the risk budget, and closes lowest-ranked positions if budget exceeded.

### RiskEngineV2
Adaptive risk budget manager. Produces a scalar `[min, base]` that
reduces risk as drawdown deepens or performance degrades. Replaces
the older fixed-budget approach.

### PerformanceState
An immutable dataclass tracking system behavioral telemetry: outcome
tracker, regime velocity (trend/shock/health), and an anticipatory scalar.
Built by `PerformanceStateBuilder` each cycle.

### PerformanceStateVelocity
A component of `PerformanceState` that analyzes outcome sequences to
detect trends (sustained win/loss streaks), shocks (sudden large losses),
and overall health → produces a scalar modifying the risk budget.

### PortfolioStateSnapshot
Immutable dataclass representing the complete portfolio exposure state
at the start of a cycle: open positions, notional values, drawdown,
factor exposures. Built by `PortfolioStateBuilder` in the PRE phase.

### RiskBudget
Immutable dataclass containing adaptive risk limits consumed by PEK:
min/max position size, remaining leverage budget, drawdown allowance.

### RecoveryScheduler
Exponential-backoff probe mechanism for halted actors. Calls `is_due()`
and `record_result()` in Phase 3h to attempt automatic recovery of
halted assets without manual intervention.

### WalWriter
The Write-Ahead Log writer (`paper_trading/replay/wal.py`) that persists
causal boundary events (features_snapshot, inference_output, decision_output)
and observability events (price_update, signal_generated, position_closed,
state_committed, actor_health) to JSONL files for deterministic replay.

### Causal Boundary Events
Three WAL event types forming a complete replay chain:
- `features_snapshot` (P0.1) — exact model input vector + feature_hash + model_hash
- `inference_output` (P0.3) — model probabilities BEFORE governance gating
- `decision_output` (P0.3) — final action AFTER all governance stages + gates bitmask

### Replay-First Architecture
Design principle where all runtime state is persisted via WAL events
with causal boundary markers (`feature_hash`, `model_hash`) enabling
deterministic reconstruction of any past cycle.

### EngineSnapshot
A frozen representation of engine state at a point in time, serialized
to `state.json` for the dashboard. Contains portfolio summary, per-asset
metrics, governance state, and admission status.

### Emergency Halt
A system-wide halt triggered by circuit breaker conditions (7 consecutive
losses or -15% drawdown). Flattens all positions and prevents new entries
until manually cleared or auto-cleared on restart (if equity ≥ 99% of peak
and reason is DRAWDOWN or CONSECUTIVE_LOSSES).

### Circuit Breaker
Multi-condition portfolio protection system:
- **Drawdown**: force-close all positions at -15% portfolio DD
- **Vol spike**: triggers on abnormal vol
- **Halt ratio**: triggers when too many assets halted
- **Consecutive losses**: triggers at 7 consecutive portfolio losses

### Schema Migration (Database)
SQLite state store (`state.db`) uses `DB_SCHEMA_VERSION = "2.0.0"`.
Migrations run at connect time via `_run_migrations()`. Current migration
(v1→v2.0.0) adds `cycle_id` to trades, `vol_spike`/`var_95` to equity_history.

---

## Governance & Risk

### Governance Layers
16 core governance mechanisms operating at different frequencies and
granularities, plus 3 adaptive budget layers (RiskEngineV2, PEK admission,
PerformanceState velocity), plus HealthMonitor circuit breaker, position
sizing guardrails, and weekend trading governance.

### Validity State Machine
Per-asset state machine (`monitoring/validity_state_machine.py`) with
three states:
- **GREEN** → full exposure (1.0×)
- **YELLOW** → reduced exposure (0.5×)
- **RED** → halted (0.0×)

Transitions use hysteresis bands, exponential inertia smoothing
(α=0.7, β=0.3), and a regime persistence lock (minimum 5 periods).

### Feature Stability
Training-window feature importances compared across retrain cycles.
Two metrics feed into the ValidityStateMachine:
- **Jaccard similarity** (top-10 features): < 0.6 → penalty
- **Spearman rank correlation**: < 0.7 → penalty

### Meta-Labeling (XGBoost)
A secondary XGBoost classifier (`labels/meta_labels.py:MetaLabelModel`)
that produces a continuous probability size scalar [0–1] from 7 features
(primary model probabilities, regime state, market structure, etc.).
Below `threshold` (0.55), notional is 0; above, maps linearly to [min_size, 1.0].
Meta-confidence is size-only — never modifies TP geometry or trailing.

### Macro Narrative Governance
Weekly LLM-driven macro context overlay: FXStreet article → Claude API →
structured JSON → governance scalars. Adjusts SL width (+10% on geopol risk)
and position size (−20% on risk_off regime). Requires human confirmation
via dashboard or auto-confirms by Monday noon.

### Narrative Pending
State where the weekly macro narrative has been fetched but awaits
human confirmation. Shown as `needs_confirmation: true` → dashboard
**NARR PENDING** button. Auto-confirms at `auto_confirm_deadline_hour`
(default Monday 12:00 ET).

### Liquidity Regime
Real-time liquidity proxy computed from daily OHLCV:
- **Volume z-score** (21d rolling)
- **Amihud illiquidity ratio** z-score
- **Corwin-Schultz spread estimate** from daily high/low

Outputs: NORMAL / THIN (SL +15%, size −15%) / STRESSED (SL +30%,
size −30%, halted).

### PSI Drift
Population Stability Index — measures distribution shift of features
between training baseline and rolling 21-day inference window. Computed
per feature per asset each cycle. NO_DRIFT (< 0.1), MODERATE (0.1–0.2,
−0.08 validity penalty), SEVERE (> 0.2, −0.20 validity penalty).
3+ SEVERE → hard halt.

### Sell Tripwire
Monitoring mechanism for SELL_ONLY assets: tracks SELL exit outcomes
in a 20-trade deque. Trips at 65% win-rate threshold (WARNING log).
Only activates when `sell_only=True` for the asset.

### Position Sizing Guardrails
Multiplicative constraints applied to every entry:
1. **Drawdown taper** — linear 1.0→min between start_dd/end_dd
2. **Per-position equity cap** — clip to `max_position_pct_of_equity`
3. **Risk-per-trade cap** — clip or skip if SL risk exceeds threshold
4. **PEK budget enforcement** (Phase 1b) — closes lowest-ranked positions
   if total notional exceeds `max_leverage × equity × tolerance`

### Multiplicative Governance Chain
The SL and size modifiers from independent governance layers stack
multiplicatively:
```
final_sl_mult = base_sl_mult × regime_geom_sl × narrative_sl_mult × liquidity_sl_mult
final_size_scalar = min(narrative_size_scalar × liquidity_size_scalar, 0.30)
```
Validity penalties (feature stability + PSI drift) are additive and feed
into the ValidityStateMachine, NOT the SL/size chain.

### Worst-Wins Aggregation
Governance penalty aggregation rule: the most negative penalty is applied
(rather than averaged). If feature stability = −0.20 and PSI = −0.08,
the combined penalty is −0.28 (additive across types).

### HealthMonitor
Portfolio-level health surveillance running in Phase 3g. Computes
portfolio volatility, VaR(95), CVaR, halt ratio, and circuit breaker checks.
Tracks per-asset health snapshots with governance scores.

---

## Portfolio Management

### Portfolio Maturity Framework (P0–P4)
Five-layer portfolio management stack:

| Layer | Component | Status |
|-------|-----------|--------|
| P0 | Weight strategies (`factor_constrained_v2`) | Enabled |
| P1 | Probability calibration (`BinnedCalibrator`) | Enabled |
| P2 | Fractional Kelly sizing | Disabled |
| P3 | Factor model (10 groups, monitoring) | Enabled for monitoring |
| P4 | HRP allocator fix (`optimal_leaf_ordering`) | Available |

### factor_constrained_v2
The active portfolio weight strategy (P0). Uses hard linear inequality
constraints (`A @ w <= b`) to enforce factor exposure limits. Binds CHF
exposure to ≤0.20 (default). Achieves total_R=124.45, Sharpe=15.40,
max_dd_R=−0.62 in walk-forward validation.

### Risk Parity
A portfolio allocation method where each asset contributes equally to
portfolio risk. EigenCapital implements `risk_parity_v1` (sample covariance)
as the baseline comparison for weight strategies.

### HRP (Hierarchical Risk Parity)
Lopez de Prado's HRP allocator that uses hierarchical clustering and
recursive bisection for weight allocation. Fixed in EigenCapital with
`optimal_leaf_ordering` for deterministic dendrogram leaf order,
preventing arbitrary weight volatility from near-singular correlation
matrices.

### BinnedCalibrator
P1 calibration method: divides [0, 1] into `n_bins` equal-width bins,
maps raw model probability → empirical P(label=1) per bin with linear
interpolation between bin centers. Reduces ECE from 0.36 → 0.02 (94.3%).

### CalibrationRegistry
Loads/saves per-asset calibrator models from `paper_trading/models/calibration/`.
Applied in the inference pipeline after `_run_inference()`, before the
decision pipeline.

### ECETracker (Expected Calibration Error Tracker)
Rolling ECE tracked per asset with configurable drift detection threshold.
ECE measures the average absolute difference between predicted probability
and observed frequency across bins.

### Kelly Criterion (P2)
Fractional Kelly sizing formula for binary bets with asymmetric payoffs:
`f* = p - q × sl_mult / tp_mult`. Edge = `p × tp_mult - q × sl_mult`.
Fractional Kelly `f = f* × 0.25` (quarter-Kelly). Disabled pending live
data validation.

### Factor Groups
10 factor exposure groups covering all 22 assets: USD, EUR, AUD, NZD,
CHF, CAD, GBP, JPY, US_EQUITY (^DJI), COMMODITY (GC). Factor exposures
computed per-cycle and exposed in `state.json` for monitoring.

### Factor Exposures
Per-group portfolio weight sums computed each cycle. Used by the
`factor_constrained_v2` weight strategy to enforce hard limits on
concentration (e.g., CHF ≤ 0.20 of portfolio).

### Conviction-Weighted
A portfolio weight method (`conviction_weighted_v1`) that tilts risk
parity allocation by model conviction scores. Higher conviction assets
receive larger allocation within risk parity constraints.

---

## Model Inference & Training

### XGBoost
The gradient boosting framework used for all per-asset models.
Configuration: `binary:logistic` objective, 300 trees, per-asset
max_depth (2–5), LR=0.02, `scale_pos_weight = imbalance_ratio`.

### AssetInferencePipeline
The per-asset inference pipeline (`paper_trading/inference/pipeline.py`)
that runs every cycle: fetch data → build features → compute regime
features → compute archetype features → PSI drift check → truncation
validation → XGBoost inference → calibration → meta-label → threshold
→ decision pipeline → execution.

### AssetTrainingPipeline
The per-asset training pipeline (`paper_trading/inference/training.py`):
fetch data → build features → triple-barrier labels → binary reduction
→ XGBoost fit → persist model → persist PSI baseline → train regime
model → train meta-label model → log importances + stability.

### RegimeConditionalModel
Per-asset regime classifier (XGBoost, 200 trees, depth=2) trained on
21 alpha features + 7 regime features. Disabled portfolio-wide since
2026-06-20 (ensemble blend not loaded at inference).

### Ensemble Blend
The 60/40 blend of base model (60%) and regime-conditional model (40%)
probabilities. Disabled after walk-forward showed −3.19R difference vs
base-only (p=0.1685, not significant). `base_weight = 1.0` in production.

### Calibration (Inference)
Post-inference probability calibration using `BinnedCalibrator`. Applied
to raw XGBoost `p_long` before the decision pipeline. Reduces ECE from
~0.36 to ~0.02. Config-gated via `calibration.enabled`.

### Scale Pos Weight
XGBoost parameter that inversely weights classes by their frequency.
Set to `n_neg / n_pos` per asset to handle imbalanced label distributions.
Part of the model training contract.

### FixedThresholdStrategy
The default signal threshold strategy: `proba[:,2] > 0.45` → BUY,
`proba[:,0] > 0.45` → SELL, both > 0.45 → BUY (long wins), neither → FLAT.
Confidence = `max(proba_long, proba_short)`.

### PurgedWalkForwardFolds
Implements CRIT-1 purging for walk-forward validation. Each fold has
an embargo gap (`max(gap, vertical_barrier)`) between training and test
sets to prevent label leakage from overlapping lookahead windows.

### Model Hash
SHA256 hash of model JSON (16 hex chars), computed at training time and
stored as a sidecar file (`{model}_hash.txt`). Used for replay determinism
verification — ensures the same model produced the logged inference output.

### Feature Hash
MD5 hash of the sorted feature dictionary (12 hex chars), computed at
inference time and threaded through the decision pipeline. Enables
cross-log consistency verification between WAL events and trace.jsonl.

### Cold-Start Transient
The first inference cycle after engine restart produces different regime
feature values (computed from 200 history rows) vs steady state (1 row).
Mitigated by `apply_first_cycle_suppression` — suppresses all trading
on cycle 1.

### Inference Truncation
When validated, truncates the feature DataFrame to 250 rows for the
XGBoost hot path (vs full 5y fetch). Significantly reduces inference
latency. Only applied when feature computation is deterministic.

---

## Features & Labels

### Alpha Features
The primary feature set built by `build_alpha_features()`. Per-asset:
9 core features (carry_vol_adj, mom_21d/63d/126d/252d, zscore_20,
vol_ratio, dow_signal, has_cot) + 6 trend-exhaustion features
(macd_hist, stoch_k, stoch_d, bb_pct_b, adx_slope, rsi_divergence)
+ 2 COT features (cot_z, cot_change_4w) + 4 cross-asset features
(dxy_mom_21d, vix_mom_5d, spx_mom_5d, WTI_mom_21d). Up to 16
additional COT features from all covered pairs are injected when
COT data is available.

### Trend-Exhaustion Features
Six indicators detecting trend maturity/exhaustion, added 2026-06-26:
MACD histogram, stochastic %K/%D, Bollinger Band %B, ADX slope,
RSI divergence. Computed via the `ta` library when OHLCV is provided.

### Cross-Asset Features
Four features derived from macro tickers: DXY 21-day return, VIX 5-day
return, SPX 5-day return, WTI crude 21-day return. Shared across all
assets.

### Regime Features
Seven features generated from OHLCV per asset: Hurst exponent,
Kaufman efficiency ratio, ADX(14), vol z-score, compression ratio,
UTC hour, session vol profile. Used by the regime-conditional model
(disabled in production).

### Archetype Features
Four inference-only features computed from full-history OHLCV:
ema_spread (EMA20−EMA50)/EMA50, ADX(14), RSI(14), bb_zscore.
Used by `ArchetypeClassifier` for trade classification; never passed
to XGBoost.

### Archetype Classifier
Classifies market structure from archetype features into categories
(MOMENTUM_IGNITION, BREAKOUT, etc.). Outputs influence TP compiler
convexity multipliers and trade admission decisions.

### Triple-Barrier Labels
The label generation method: first touch of TP (+1), SL (-1), or
vertical barrier expiry → {−1, 0, 1}. Binary reduction drops HOLD (0)
and maps {−1, 1} → {0, 1} for XGBoost training. Per-asset pt_sl
from per-asset YAML files.

### COT Features
Commitments of Traders positioning data features: `cot_z` (speculative
positioning z-score) and `cot_change_4w` (4-week change in net
positioning). Available for CFTC-covered pairs. All COT-covered pair
features are injected into every asset's feature vector (known tech debt).

### Custom Feature Variants
Assets with additional or replacement features beyond the base set:
EURCHF/NZDUSD use `mom126` (replaces base mom), GBPAUD/CADCHF/EURNZD/
GBPCHF use `yield_slope` (US yield curve slope).

### MACD Histogram
Trend-exhaustion feature: MACD line minus signal line, normalized by
close price. Clipped to ±5% for scale invariance across assets.

### RSI Divergence
Binary trend-exhaustion feature: detects bullish (+1) or bearish (−1)
divergence between price and RSI using local extrema within a 20-bar
lookback window. From `features/divergence.py`.

### Bollinger Band %B
Trend-exhaustion feature: `(close - lower_band) / (upper_band - lower_band)`.
Indicates price position within the Bollinger Band range.

### ADX Slope
Trend-exhaustion feature: rate of change of ADX over 5 days. Measures
trend acceleration or deceleration.

### Stochastic %K/%D
Trend-exhaustion features: stochastic oscillator %K (normalized to [0,1])
and its signal line %D. Indicates overbought/oversold conditions.

### COT Data Injection
COT features from all ~16 CFTC-covered pair columns are joined into
every asset's feature vector regardless of whether the asset is a COT
pair. Assets not in COT data (GC, ES, NQ) receive unrelated COT data.
Flagged as tech debt.

### Vertical Barrier
The maximum number of bars a trade is held before forced exit (default 20).
Configurable per-asset. Used in triple-barrier labeling and the gap
(embargo) calculation for walk-forward validation.

### Label Inversion
Experimental technique for diagnosing BUY signal inversion: swap label
mapping so y' = 1 - y (treat BUY targets as SELL). EURAUD BUY WR only
improved from 22.7%→31.0%, confirming the inversion is not a label
artefact.

---

## Metrics & Statistics

### Sharpe Ratio (Autocorrelation-Adjusted)
The Sharpe ratio adjusted for autocorrelation using the Lo (2002)
correction: `Sharpe_adj = Sharpe × sqrt((1-ρ) / (1+ρ))` where ρ is
the first-order autocorrelation of returns. Essential for high-frequency
(30s cycle) returns where autocorrelation is significant.

### Information Coefficient (IC)
The rank correlation between model predictions and actual outcomes.
Measures the model's ability to rank-order assets by expected return.
IC > 0 indicates predictive skill. Used in walk-forward validation.

### Hit Rate (HR)
The fraction of predictions that correctly forecast the direction of
next-period returns. Complement to win rate, used for promotion scoring.

### Win Rate (WR)
The fraction of trades that close with positive R-multiple. Distinguished
from breakeven win rate (BE WR) which accounts for TP/SL asymmetry.

### Total_R
The sum of all R-multiples across a set of trades. The primary portfolio
performance metric. Expressed in R-units (dimensionless).

### Max_DD_R
The maximum peak-to-trough drawdown in R-multiple space. Expressed as
a negative number (e.g., −0.15R means 0.15R drawdown from peak).

### Profit Factor (PF)
The ratio of total winning R to total losing R: `Σwins / |Σlosses|`.
PF > 1.0 indicates profitability. Used as a hard gate for asset promotion.

### Expected Calibration Error (ECE)
The average absolute difference between predicted probability and
observed frequency across bins. A perfectly calibrated model has ECE=0.
EigenCapital calibration reduces ECE from 0.36 → 0.02.

### MFE (Maximum Favorable Excursion)
The maximum profit (in R) a trade reached before being closed. Used to
evaluate exit strategy quality — high MFE + low return suggests premature
exit. Central metric for the adaptive exit engine validation.

### MAE (Maximum Adverse Excursion)
The maximum loss (in R) a trade reached before recovering. Used to
evaluate stop-loss placement and trade selection.

### Efficiency Score (Trade Efficiency)
Ratio of captured R to MFE: `captured_R / MFE`. Higher values indicate
the exit strategy captured more of the available profit. 62% average
across the portfolio before adaptive exit engine.

### Risk-Adjusted Return (RAR)
Return per unit of risk, measured as Sharpe or Sortino ratio. EigenCapital
distinguishes between R-multiple Sharpe (signal quality metric, not
comparable to financial Sharpe) and %-return Sharpe (simulated portfolio
return metric).

### VaR(95) / CVaR(95)
Value at Risk (5th percentile of portfolio returns) and Conditional
VaR (mean of the tail beyond VaR). Computed on a rolling 60-period
window in Phase 3h. Expressed as fraction of portfolio equity.

### PSR / DSR (Probabilistic / Deflated Sharpe Ratio)
Statistical significance metrics for Sharpe ratios. PSR(>0) tests whether
Sharpe > 0; DSR adjusts for multiple testing (number of assets/trials).
Both saturate at 1.0 for Sharpe > 0.3 (n≈250) due to float64 limits.
Useful only for Sharpe in [0.0, 0.8] range.

### MinTRL (Minimum Track Record Length)
The minimum number of observations needed to be 95% confident that the
observed Sharpe ratio is positive. Floors at 2 for extreme Sharpe values.
Useful range is Sharpe in [0.1, 2.0].

### Calmar Ratio
Annualized return divided by maximum drawdown. Measures return per unit
of drawdown risk. Higher values indicate better risk-adjusted returns.

### Sortino Ratio
Similar to Sharpe but uses downside deviation (only negative returns)
instead of total standard deviation. Penalizes only harmful volatility.

### CMSS (Composite Model Stability Score)
The mean stability score across all 12 adversarial perturbations in the
adversarial manifold test. Classification: ROBUST (≥ 0.7), MODERATE
(≥ 0.5), BRITTLE (< 0.5).

### MAS (Model Assessment Score)
Composite score [0–100] combining 6 sub-scores: model (0.20), signal
(0.20), portfolio (0.20), shadow (0.15), forward (0.15), stress (0.10).
Used for model comparison and promotion decisions.

### FQI (Fill Quality Index)
Composite fill quality metric: `fill_ratio × gap_penalty × partial_penalty
× latency_penalty`. Component of the execution quality dashboard.

### EIS (Execution Impact Score)
Composite execution quality metric: `slippage(40%) + fill_quality(35%)
+ latency(25%)`. Shown in the dashboard ExecutionQualityStrip.

---

## Execution & Broker

### MT5 Bridge
The TCP frame protocol connecting the EigenCapital engine to MetaTrader 5
running under Wine. Host: `paper_trading/ops/mt5_client.py`, Bridge:
`paper_trading/ops/mt5_bridge.py` (Wine Python). Port 9879.

### MT5Broker
The broker interface implementation that routes orders to MT5 via the bridge.
Implements `BrokerInterface` with `place_order()`, `close_position()`,
`modify_position()`, `get_positions()`, `get_current_price()`,
`get_account_summary()`.

### PaperBroker
The simulated broker interface for paper trading. Executes fills at
current market price without slippage (slippage/impact are post-hoc
attribution layers).

### BrokerInterface
Abstract base class defining the broker contract: place_order,
close_position, modify_position, get_positions, get_current_price,
get_account_summary.

### PositionManager
Per-asset position lifecycle manager (`PaperPositionManager`). Handles
open, close, flip, stop-loss/take-profit updates, trailing stops, and
scale-out tier tracking.

### MT5 Orphan
A position on the MT5 broker side with no corresponding paper-side ticket.
Detected and handled by Phase C/D of the orchestrator cycle. Self-healing
adoption backfills `mt5_ticket` from broker Position objects.

### DynamicSLTPEngine
Live SL/TP barrier computation engine using ATR-based volatility.
`_atr_barriers()` computes SL and TP distances from entry price using
ATR_pct, atr_mult_sl, atr_mult_tp. TP is overridden by the TP compiler
for live orders.

### ShadowSLTPEngine
Counterfactual SL/TP engine for running alternative exit strategies
in shadow mode alongside live exits. Results don't affect positions.

### EntryService
Entry validation service implementing the full sizing chain: Kelly
multiplier → drawdown taper → position cap → risk cap → min viable gate.
Also validates price deviation (`max_entry_slippage_pct`) and manages
deferred entry queue.

### TP Compiler
`paper_trading/entry/tp_compiler.py:compute_take_profit()` — ALWAYS
overrides the ATR-based TP distance with:
```
tp_distance = sl_distance × convexity × reg_mult × tp_mult_override
```
Capped at `MAX_RR = 5.0`. Generates scale-out tier profiles dynamically.

### Post-Entry Adjustment
Within the first `post_adjust_interval_bars` (default 3), `post_entry_adjust()`
recomputes barriers based on current ATR. Vol spikes (>1.3×) tighten SL;
vol collapses (<0.7×) no action.

### Attributation Collector
Captures per-trade attribution across 4 domains: Prediction (model quality),
Execution (fill quality), Exit (exit strategy), Friction (slippage/latency).
Used by the execution dashboard's PnL waterfall chart.

### MT5 Symbol Map
YAML file (`configs/mt5_symbol_map.yaml`) mapping EigenCapital tickers
to MT5 symbol names (e.g., `GC=F` → `XAUUSD`). Required for MT5 bridge
order placement.

### OrderType
Enumeration of order types used in the engine: MARKET, LIMIT, STOP,
STACK (for pyramiding layers). Influences execution routing and MT5
orphan detection.

---

## Configuration & Infrastructure

### EngineConfig
The runtime configuration object produced by `PaperConfigRegistry.load()`.
Contains all system parameters: capital allocation, asset list, per-asset
SL/TP/depth, governance settings, mode overrides, and more.

### PaperConfigRegistry
The typed configuration registry (`configs/paper_config_registry.py`)
that loads YAML from the domain tree, applies mode overlays, resolves
per-asset overrides, and produces a unified `EngineConfig`. The sole
source of truth for all configuration.

### Active Mode
The currently selected operating mode (production, challenge_ftmo_10k,
or live). Set via `mode:` key in the mode YAML file. Controls capital
allocation, risk limits, drawdown limits, and factor exposure ceilings.

### Environment Overlay
Configuration layer that applies environment-specific overrides (paper,
live, backtest, research). Selected via `EIGENCAPITAL_ENV` env var or
the mode selector. Controls data_source, rebalance frequency, research_mode.

### Mode Overlay
Configuration layer defined in `configs/domains/modes/<name>.yaml`.
Merges on top of the base domain config to provide mode-specific
capital, sizing, drawdown, and factor exposure parameters.

### Legacy Mirror
`tools/config_mirror_legacy.py` — tool that regenerates the legacy
`paper_tracking.yaml` from the registry for debugging/comparison.
Supports `--write`, `--check`, and `--ci` modes.

### Config Diff
`tools/config_diff.py` — side-by-side YAML comparison tool with
`--json` for CI integration. Detects structural, value, and key changes
between two configurations.

### Schema Version
`configs/schema_version.json` tracks the configuration schema version
(current: `2.0.0`). Checked at load time by `PaperConfigRegistry` and
`check_config_schema.py`. Bumped for backward-incompatible changes.

### Import Firewall
`tools/check_import_firewall.py` — CI tool that prevents forbidden
cross-module imports (e.g., `paper_trading/` importing from `dashboard/`).
Ensures module boundary integrity.

### Doc Drift Check
`tools/doc_drift_check.py` — CI tool that verifies documentation
consistency: that the asset list in documentation matches the actual
config, SELL_ONLY sets match, and other cross-referenced invariants.

### Bridge Supervisor
`scripts/ops/mt5_bridge_supervisor.py:BridgeSupervisor` — systemd-level
watchdog for the MT5 bridge. Monitors via JSON-RPC heartbeat, restarts
on consecutive failures, capped restart count. Exposes `/health` and
`/ready` endpoints.

### ATLAS Detector
`eigencapital/observability/atlas.py:AtlasDetector` — layered change-point
detector combining CUSUM (cumulative sum control chart), Page-Hinkley
test, and sliding-window Kolmogorov-Smirnov test. Monitors for covariate
shift in feature distributions.

### CUSUM (Cumulative Sum Control Chart)
A sequential change-point detection algorithm that accumulates deviations
from a target mean. Part of the ATLAS detector. Fires when cumulative
divergence exceeds a threshold scaled by observed standard deviation.

### Page-Hinkley Test
A symmetric drift detection algorithm that tracks running minimum
cumulative deviation. Part of the ATLAS detector. Complements CUSUM
by detecting gradual drifts.

### Kolmogorov-Smirnov Test (Sliding Window)
A non-parametric test comparing feature distributions between adjacent
time windows. Part of the ATLAS detector for detecting distributional
changes without parametric assumptions.

### Chaos Framework
`tests/chaos/chaos_tools.py` — deterministic fault injection framework
supporting count-limited failures, probability-controlled failures,
custom exceptions, return overrides, and latency simulation. Uses
`FaultRecipe` + `fault_inject` context manager with nesting support.

### Prometheus Metrics
Engine metrics exposed at `/metrics` endpoint (port 5000). Uses
lightweight exposition format (v0.0.4), no dependency on prometheus_client.
Pre-seeded with `eigencapital_engine_*` namespace metrics.

---

## Dashboard & UI

### TickerRail
The 32px-tall mono breadcrumb above the header on every route. Displays:
`EC · EIGENCAPITAL · seq #N · engine <state> · tick <N>s · pek <a>/<i> ·
halt <yes|no> · assets <N>`. Morphs to a halt-channel during emergency halt.

### State.json
The real-time engine state snapshot served by the dashboard API (`/state.json`).
Contains portfolio summary, per-asset metrics, governance state, admission
status, factor exposures, and live Sharpe data.

### Anchor Nav
Sticky horizontal navigation bar (Portfolio/Signals/Execution/Trades/
Governance/Risk/Charts). Uses `IntersectionObserver` for scroll-linked
section highlighting.

### ConnectionStatus Bar
Header bar monitoring 5 endpoints (`/ping`, `/state.json`, `/narrative.json`,
`/governance.json`, `/risk_parity.json`). Shows Live (green), Degraded
(yellow, 1-2 failing), or Offline (red, 3+ failing). Hover tooltip for
per-endpoint status.

### AlertFeed
Real-time governance event capture: halt state changes, PSI-SEVERE alerts.
Persisted in `sessionStorage`. Dismissible per-event with severity badge.

### PSI Drift Panel
Dashboard panel showing per-asset feature distribution shift scores with
color-coded classification badges (green/amber/red) and trend arrows
(↑ stable, ↓ improving, → steady). Table format with feature rows.

### EquityCurveSparkline
80px SVG chart on the CommandCenter showing the portfolio equity curve
from `/equity_history.json`. Glance-level view of portfolio health.

### ExecutionQualityStrip
Dashboard KPI row showing EIS and FQI per asset. Layer 1 of the
execution dashboard anchor section.

### Attribution Breakdown
Domain scores grid (Prediction/Execution/Exit/Friction) + PnL Waterfall
bar chart decomposing gross PnL into prediction contribution, execution
cost, friction cost, and net.

### NARR PENDING / NARR ERR
Dashboard badges for macro narrative status. **NARR PENDING** (clickable
button) when narrative awaits confirmation. **NARR ERR** (yellow/red)
when scrape or LLM call fails. **(STALE)** suffix when narrative exceeds
7-day window.

### LIQ THIN / LIQ STRSD
Dashboard badges for liquidity regime state. **LIQ THIN** (yellow badge)
when one or more assets in THIN regime. **LIQ STRSD** (red badge) when
any asset in STRESSED regime. Hover tooltip shows per-asset breakdown.

### Governance Rows
Per-asset governance summary cards with left-border accent strip colored
by premature-stop classification (GREEN/YELLOW/RED). RED rows have an
animated pulse ring.

### RiskParityPanel
Bar chart showing target allocations colored by governance state
(RED/YELLOW/GREEN). Equal-weight reference line. Total allocation footer.

---

## Acronyms Quick Reference

| Acronym | Full Name | Category |
|---------|-----------|----------|
| ADR | Architecture Decision Record | Documentation |
| ADX | Average Directional Index | Technical Indicator |
| ATR | Average True Range | Volatility Metric |
| AUC | Area Under the Curve | Model Metric |
| BB | Bollinger Bands | Technical Indicator |
| BE | Breakeven | Trading Concept |
| CMSS | Composite Model Stability Score | Model Metric |
| COT | Commitments of Traders | Fundamental Data |
| CVaR | Conditional Value at Risk | Risk Metric |
| DD | Drawdown | Risk Metric |
| DSR | Deflated Sharpe Ratio | Statistical Metric |
| DXY | US Dollar Index | Macro Index |
| ECE | Expected Calibration Error | Model Metric |
| EIS | Execution Impact Score | Execution Metric |
| EMA | Exponential Moving Average | Technical Indicator |
| EWMA | Exponentially Weighted Moving Average | Statistical Method |
| FQI | Fill Quality Index | Execution Metric |
| F/X | Foreign Exchange | Asset Class |
| HR | Hit Rate | Model Metric |
| HRP | Hierarchical Risk Parity | Portfolio Method |
| IC | Information Coefficient | Model Metric |
| KS | Kolmogorov-Smirnov | Statistical Test |
| LR | Learning Rate | ML Parameter |
| MACD | Moving Average Convergence Divergence | Technical Indicator |
| MAE | Maximum Adverse Excursion | Trade Metric |
| MAS | Model Assessment Score | Model Metric |
| MFE | Maximum Favorable Excursion | Trade Metric |
| MinTRL | Minimum Track Record Length | Statistical Metric |
| ML | Machine Learning | General |
| MT5 | MetaTrader 5 | Trading Platform |
| OOS | Out-of-Sample | Validation |
| PnL | Profit and Loss | Trading Concept |
| PEK | Portfolio Execution Kernel | System Component |
| PF | Profit Factor | Trading Metric |
| PSI | Population Stability Index | Statistical Test |
| PSR | Probabilistic Sharpe Ratio | Statistical Metric |
| RMS | Root Mean Square | Statistical Metric |
| RSI | Relative Strength Index | Technical Indicator |
| SHAP | SHapley Additive exPlanations | Model Explanation |
| SL | Stop Loss | Order Type |
| SLSQP | Sequential Least Squares Programming | Optimization |
| SMA | Simple Moving Average | Technical Indicator |
| SPA | Single Page Application | Architecture |
| SPX | S&P 500 Index | Macro Index |
| SQLite | SQLite Database Engine | Persistence |
| TP | Take Profit | Order Type |
| TZ | Timezone | Data Concept |
| UTC | Coordinated Universal Time | Time Standard |
| VaR | Value at Risk | Risk Metric |
| VIX | Volatility Index | Macro Index |
| WAL | Write-Ahead Log | Persistence |
| WF | Walk-Forward | Validation |
| WR | Win Rate | Trading Metric |
| WTI | West Texas Intermediate | Commodity |
