# EigenCapital — Risk & Governance Layer

16 core governance mechanisms (plus 3 adaptive budget layers: RiskEngineV2, PEK admission controller, PerformanceState velocity), plus decision pipeline suppression stages, position sizing guardrails, HealthMonitor circuit breaker, and weekend trading governance, operating at different frequencies and granularities.

## Governance Layers (16 core)

| Layer | Frequency | Scope | Effect |
|---|---|---|---|
| Validity state machine | Per tick | Per asset | Exposure 0–100% |
| Feature stability | Per retrain | Per asset | Validity penalty |
| Meta-labeling (XGBoost) | Per signal | Per asset | Continuous size scalar [0–1] |
| Macro narrative | Weekly | Global | SL width, position size |
| Liquidity regime | Per signal | Per asset | THIN: SL +15%, size −15% (soft) |
| | | | STRESSED: SL +30%, size −30%, halt |
| PSI drift | Per cycle | Per asset | Validity penalty, halt at 3+ SEVERE |
| Sell-only filter | Per decision | Per asset | Override BUY→FLAT for 3 inverted-BUY assets (CADCHF, NZDCHF, EURAUD) |
| Calibration (P1) | Per inference | Per asset | Remap raw p_long via BinnedCalibrator, ECE 0.36→0.02 |
| Kelly sizing (P2) | Per decision | Per asset | Scale position by Kelly criterion (config-gated, disabled) |
| Factor model (P3) | Per cycle | Portfolio | Factor exposures via 9 groups in state.json (monitoring only) |
| Position concentration | Per cycle | Portfolio | Flags >75% net-short skew (recommendation) |
| Circuit breaker | Per cycle | Portfolio | Multi-condition: dd, vol spike, halt ratio, consecutive losses (threshold=7) |
| Portfolio drawdown | Per cycle | Global | Circuit breaker at −15% |
| Entry price deviation | Per entry | Per asset | Skip entry if price drifted >2% |
| Profit lock | Per flip | Per asset | Block flip if PnL >15% |
| Weekend trading governance | Per cycle | Per asset (eligible) | Filtered cycle for `weekend_eligible` assets; 0.5× allocation multiplier; `crypto: [0,24]` session tier |

| RiskEngineV2 (adaptive budget) | Per cycle | Portfolio | Scalar → adaptive risk budget [min, base]; reduces risk as drawdown deepens or performance degrades |
| PEK admission controller | Per cycle | Portfolio | Collect intents → fast filter (hard gates) → rank (composite score) → allocate budget → close over-budget |
| PerformanceState velocity | Per cycle | Portfolio | Outcome tracker + velocity processor (trend, shock, health) → anticipatory scalar ∈ [0.5, 1.5] |

**Live VaR/CVaR:** Rolling 60-period portfolio returns → VaR(95)=5th percentile, CVaR=mean of tail, computed in Phase 3h.

**RecoveryScheduler:** Exponential-backoff probe of halted actors via `is_due()`/`record_result()` in Phase 3g.

## Decision Pipeline Stages (`DEFAULT_STAGES` order)

Each stage is a standalone function operating on `DecisionContext`. Stages are chained by `run_decision_pipeline()` in `paper_trading/execution/decision_pipeline.py`. A stage blocks entry by setting `ctx.new_side = None`; an abort (`ctx.abort = True`) halts all remaining stages and returns `None`. Block counts per stage are tracked via `_gate_blocked_counts` and exposed as Prometheus `eigencapital_engine_gate_blocked_total`.

| Stage | Effect | Thresholds / Config | Fail Mode |
|-------|--------|-------------------|-----------|
| First-cycle suppression | Suppress all trading on cold-start cycle 1 | Triggers when `_cycle_counter <= 1` | Abort (halt pipeline) |
| Bar-jump suppression | Suppress acting on signals for 60 min after bar count changes >100 (e.g., yfinance→MT5 source switch) | `BAR_JUMP_SUPPRESS_MINUTES = 60` | Suppresses signal |
| Store prediction metadata | Record `_last_label`, `_last_confidence`, `_last_prob_long/short/neutral`, `_entry_archetype` on engine | No config | Non-blocking |
| Update MAE/MFE | Update max adverse/favorable excursion for open positions using `high`/`low` from OHLCV DataFrame | Reads `ctx.df["high"]`, `ctx.df["low"]` | Non-blocking (logs warning on failure) |
| Resolve signal | Convert `SignalType` to `PositionSide`: BUY→LONG, SELL→SHORT, else FLAT | `SignalType` enum (see `entry/decision.py`) | Sets `new_side = None` |
| Risk-off suppression | Flat AUDUSD when risk-off detected (VIX rising + SPX falling) | `RISK_OFF_ASSETS = {"AUDUSD"}`; reads `engine._risk_off` flag | Suppresses signal |
| VIX gate | Suppress CL=F when VIX > 30. Fail-open if VIX data missing or >5 days stale. | `VIX_GATE_THRESHOLD = 30.0`; `VIX_GATE_ASSETS = {"CL"}`; stale check: 5d | Fail-open (allow entry when data unavailable) |
| Sell-only filter | Override BUY→FLAT for `SELL_ONLY_ASSETS` (CADCHF, NZDCHF, EURAUD). Force-closes any stale LONG positions from pre-filter era. | Assets resolved via `get_sell_only_assets()` from `execution/gate_constants.py` | Suppresses BUY signal; force-closes LONG |
| Spread gate | Block new entry if live spread (bps) exceeds per-asset-class threshold. Observe-only for first 720 cycles (~6h). Fail-closed post-observe — missing/stale spread data blocks entry. | `SPREAD_TIER_BPS`: fx_major=10, fx_cross=20, indices=15, metals=20; staleness=300s | Fail-closed post-observe |
| Session gate | Block new entry outside session windows per asset-class tier. Observe-only for first 720 cycles. | Tiers: fx_major (7-17 UTC), fx_cross (7-17), indices (13-20), metals (8-18), crypto (0-24) | Blocks outside window post-observe |
| ADX entry gate | Block new entry when ADX < threshold (choppy market). Disabled by default; observe-only by default when enabled. | `ADX_ENTRY_GATE_DEFAULT_THRESHOLD = 18`; config key: `adx_entry_gate` with `enabled`, `adx_threshold`, `observe_only` | Observe-only by default |
| Confidence gate | Skip trade if signal confidence below per-asset `min_confidence` threshold | Config key: `min_confidence` (per-asset override, global default 55.0) | Sets `new_side = None` |
| Signal hysteresis | Require 2-of-3 latest signals to agree before allowing position flip | `HYSTERESIS_WINDOW = 3`, `HYSTERESIS_MIN_AGREE = 2` | Blocks flip |
| Meta-label advisory | Record meta-label recommendation (no enforcement). Logs when `prob < threshold`. | Config key: `meta_labeling.enabled`; threshold from `meta_label_model.threshold` | Advisory only (no gate) |
| Update regime bar counter | Increment `_regime_bar_counter` each cycle in same regime; reset to 1 on regime change | Reads `engine._current_regime` vs `_last_regime_label` | Non-blocking |
| Conviction gate | Evaluate flip gate via `_evaluate_flip_gate()` based on regime conviction | See `engine._evaluate_flip_gate()` | Blocks flip |
| Kelly sizing (P2) | Apply fractional Kelly multiplier from calibrated probability and tp/sl. Skips if calibration not applied upstream (raw XGBoost softmax is unreliable). | Config key: `kelly.enabled` (default false); `fraction=0.25`, `max_cap=1.0`, `min_edge=0.0` | Sets `new_side = None` if multiplier <= 0 |
| Manage position | Position protection (breakeven lock at 0.5R, trailing), entry gate check, profit lock (blocks flip if unrealized PnL > 15%), stacking gate, max positions per asset | Config keys: `stacking.enabled`, `max_positions_per_asset`, `profit_lock_threshold_pct=15.0` | Blocks entry or flip |
| Build entry artifacts | Run structure detection + entry optimizer; compute SL/TP via `compute_effective_multipliers` + `compute_take_profit`; optionally create `DeferredEntry` | Config key: `dynamic_sltp.enabled`, `entry_defer_max_bars=5` | Sets `new_side = None` on import failure |
| Route execution policy | Handle ENTER/DEFER/SKIP action via `ExecutionPolicy`. ENTER → `_open_position()`; DEFER → `_pending_entries[]` | Reads `engine._execution_policy` | Logs action reason |
| Poll deferred entries | Execute pending deferred orders from previous cycles | Calls `engine._poll_pending_entries(ctx.df)` on each cycle | Non-blocking |
| Update prob history | Append signal + confidence to `prob_history` (max 1000 entries); update confidence buckets | `MAX_PROB_HISTORY = 1000` | Non-blocking |

Stage source: `DEFAULT_STAGES` list in `paper_trading/execution/decision_pipeline.py:967-990`.

## Position Sizing Guardrails

Applied multiplicatively in entry sizing:
1. Drawdown taper — linear 1.0→min between start_dd/end_dd
2. Per-position cap — clip to max_position_pct_of_equity
3. Risk-per-trade cap — clip or skip if SL risk exceeds max_risk_per_trade_pct

PEK budget enforcement (Phase 1b) replaces the old leverage budget + backstop:
total notional across all positions must not exceed max_leverage × equity × tolerance.
If exceeded, lowest-ranked admitted positions are closed until within budget.

## 1. Validity State Machine

Each asset runs an independent validity state machine in `monitoring/validity_state_machine.py`:

- **GREEN** → full exposure (1.0×)
- **YELLOW** → reduced exposure (0.5×)
- **RED** → halted (0.0× — no PnL accrual)

Transitions use **hysteresis bands**, **exponential inertia smoothing**, and a **regime persistence lock** to prevent rapid state flipping. Input signals:

- Drawdown vs threshold
- Monthly profit factor
- Signal drought (days since last signal)
- Confidence drift from expected baseline

**Exposure gating**: Each tick, `run_once()` calls `update_validity()` and sets `pos_mgr.exposure_multiplier` to the state machine's output. This directly scales all PnL calculations — GREEN=full, YELLOW=half, RED=flat.

## 2. Feature Importance Stability

Training-window feature importances are persisted per asset per retrain cycle. Two metrics feed into the ValidityStateMachine:

- **Jaccard similarity** (top-10 features): < 0.6 → −0.10 penalty, < 0.4 → −0.25 penalty
- **Spearman rank correlation** (shared features): < 0.7 → −0.08 penalty, < 0.5 → −0.20 penalty
- **Worst-wins aggregation**: the most negative penalty is applied (not averaged)

## 3. Meta-Labeling Layer (XGBoost)

A secondary confidence filter applied after the primary XGBoost signal:

- **Model**: XGBoost XGBClassifier (`labels/meta_labels.py:MetaLabelModel`)
- **Features** (7): primary model probabilities, regime state, periods in state, stability penalty, close price, archetype, market structure
- **Decision**: continuous probability — below `threshold` (0.55 for most assets) → zero notional; above → `_meta_size_multiplier()` maps [threshold, 1.0] → [min_size, 1.0] linearly
- **Integration**: `_last_meta_proba` fed into `_composite_size_scalar()` alongside governance scalars; meta-confidence is size-only — never modifies TP geometry, trailing, or scale-out schedules

**Historical note:** An earlier LogisticRegression implementation (`shared/meta_labeling.py`) was superseded after AUC 0.49-0.55 validation (effectively random). The file remains on disk but is not used in production — all live meta-labeling runs through the XGBoost path in `labels/meta_labels.py`. The XGBoost replacement uses richer features and continuous sizing to avoid the hard ENTER/BLOCK switching that made the old approach fragile.

## 4. Macro Narrative Governance (Weekly)

Weekly LLM-driven macro context overlay that adjusts execution parameters based on FXStreet analysis:

- **Pipeline**: FXStreet "Week ahead" article → Claude API (structured JSON extraction) → `MacroNarrativeFeatures` → governance scalars
- **Regime output**: `risk_off`, `geopol_tension`, `risk_on`, `data_driven` — derived from geopol risk score, fed/central bank hawkishness, currency biases
- **Governance rules** (via `narrative_governance_scalars()`):
  - `geopol_risk_score > 0.7` → SL widens by `geopol_sl_widen_pct` (default +10%)
  - `overall_regime == "risk_off"` → position size reduces by `risk_off_size_reduce_pct` (default -20%)
  - `confidence < min_confidence` (default 0.6) or stale narrative → no governance applied
- **Human review step**: Narrative lands as `data/live/narrative_pending.json`; must be confirmed via dashboard **NARR PENDING** button or auto-confirms at Monday noon (`auto_confirm_deadline_hour: 12`)
- **Staleness**: ≥7 days since week_start → stale flag suppresses governance, shown as `(STALE)` on dashboard
- **Failure mode**: scrape/LLM error → narrative carries forward with `fetch_error` status; dashboard shows yellow **NARR ERR** badge
- **Integration**: `_narrative_sl_mult` multiplied into SL in `_open_position`; `_narrative_size_scalar` applied in `_sizing_config` and execution bridge notional; `narrative_ok` flag in `check_halt_conditions` with -0.10 validity penalty
- **State storage**: `data/live/narrative_active.json`, `data/live/narrative_pending.json`
- **Config**: `configs/domains/governance/narrative.yaml` — loaded by `PaperConfigRegistry` and composed into `execution.governance.*`
- **Requires**: `OPENCODE_ZEN_API_KEY` env var

## 5. Liquidity Regime Model (Per-Tick)

Real-time liquidity proxy computed from daily OHLCV on every signal cycle:

- **Features** (`compute_liquidity_features()`):
  - **Volume z-score**: rolling 21d z-score of volume (negative = thin)
  - **Amihud illiquidity ratio z-score**: `|return| / (volume × close)`, normalized (positive = illiquid)
  - **Corwin-Schultz spread estimate**: bid-ask spread proxy from daily high/low
- **Regime output**: `NORMAL` / `THIN` / `STRESSED` — threshold-driven from config params
- **Governance rules** (via `liquidity_governance_scalars()`):
  - `THIN` → SL widens by `thin_sl_widen_pct` (+15%), size reduces by `thin_size_reduce_pct` (-15%)
  - `STRESSED` → SL widens by `stressed_sl_widen_pct` (+30%), size reduces by `stressed_size_reduce_pct` (-30%), sets halted flag
- **Integration**: `_liquidity_sl_mult` multiplied into SL in `_open_position`; `_liquidity_size_scalar` applied in sizing and execution notional; `liquidity_ok` flag in `check_halt_conditions` (STRESSED halts) with -0.10 validity penalty
- **Dashboard**: LIQ THIN (yellow) / LIQ STRSD (red) badge in header with per-asset hover tooltip
- **Config**: `configs/domains/governance/liquidity.yaml` — loaded by `PaperConfigRegistry` and composed into `execution.governance.*` with threshold and pct params

## 6. PSI Drift Monitoring (Per-Cycle)

Automated distribution shift detection per feature per asset:

- **Core** (`monitoring/psi_monitor.py`):
  - `compute_psi()` — fixed-width bins from baseline min/max, first/last bin extended to ±inf for overflow
  - `classify_drift(psi)` — NO_DRIFT (< 0.1), MODERATE (0.1 – 0.2), SEVERE (> 0.2)
  - `PSIDriftEntry` dataclass per feature with `psi`, `classification`, `trend` (STABLE / INCREASING / DECREASING vs previous cycle), `importance_score`
  - `PSISnapshot` dataclass per asset with per-feature list, worst_classification, moderate_count, severe_count, psi_ok, penalty
- **Baseline**: Training window feature distribution persisted to `data/live/psi_baseline/{asset}.parquet` immediately after `model.fit()` — only updated on retrain
- **Current window**: Rolling 21-day inference feature distribution, computed each cycle from `features_df.tail(21)`
- **Feature scoping**: Only top-10 most important features per asset (from `importance_store`)
- **Governance rules**:
  - Any MODERATE feature → −0.08 validity penalty
  - Any SEVERE feature → −0.20 validity penalty (penalties additive: max −0.28 combined)
  - 3+ SEVERE features → `psi_ok = False`, hard halt on asset
  - Trend arrow (↑↓→) on dashboard distinguishes data glitch (single SEVERE, STABLE trend) from genuine drift (SEVERE + INCREASING)
- **Penalty accumulation**: PSI penalty is additive with feature stability penalty (both are separate terms in `update_validity()`) — worst-wins at each penalty type, summed across types
- **Dashboard**: `GET /psi.json` — per-asset table with color-coded feature rows, trend arrows, classification badges, worst-classification summary, collapsible halted section
- **Endpoint**: `GET /psi.json` (30s cache)

## Multiplicative Governance Chain

The SL layers stack multiplicatively on the existing SL chain:

```
final_sl_mult = base_sl_mult × regime_geom_sl × narrative_sl_mult × liquidity_sl_mult
final_size_scalar = min(narrative_size_scalar × liquidity_size_scalar, 0.30)
```

Validity penalties (feature stability + PSI drift) are additive and feed into the validity state machine, NOT into the SL/size chain:

---

**Last updated:** 2026-07-05

```
validity_score = 0.80 − drawdown_penalty − pf_penalty − drought_penalty − drift_penalty − narrative_penalty − liquidity_penalty + stability_penalty + psi_penalty
```

Each layer is independently configurable, independently gated (by confidence, staleness, or threshold), and independently observable in the dashboard.
