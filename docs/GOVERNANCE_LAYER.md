# QuantForge — Risk & Governance Layer

11 independent governance mechanisms, plus decision pipeline suppression stages, position sizing guardrails, and HealthMonitor circuit breaker, operating at different frequencies and granularities.

## Governance Layers (11 + HealthMonitor)

| Layer | Frequency | Scope | Effect |
|---|---|---|---|
| Validity state machine | Per tick | Per asset | Exposure 0–100% |
| Feature stability | Per retrain | Per asset | Validity penalty |
| Meta-labeling (XGBoost) | Per signal | Per asset | Continuous size scalar [0–1] |
| Macro narrative | Weekly | Global | SL width, position size |
| Liquidity regime | Per signal | Per asset | THIN: SL +15%, size −15% (soft) |
| | | | STRESSED: SL +30%, size −30%, halt |
| PSI drift | Per cycle | Per asset | Validity penalty, halt at 3+ SEVERE |
| Sell-only filter | Per decision | Per asset | Override BUY→FLAT for 8 inverted-BUY assets |
| Equity cluster alarm | Per cycle | Global | Flags ES/NQ/^DJI all same side (recommendation, 60s throttle) |
| Circuit breaker | Per cycle | Portfolio | Multi-condition: dd, vol spike, halt ratio, consecutive losses (threshold=7) |
| Portfolio drawdown | Per cycle | Global | Circuit breaker at −15% |
| Entry price deviation | Per entry | Per asset | Skip entry if price drifted >2% |
| Profit lock | Per flip | Per asset | Block flip if PnL >15% |

**Live VaR/CVaR:** Rolling 60-period portfolio returns → VaR(95)=5th percentile, CVaR=mean of tail, computed in Phase 3g.

**RecoveryScheduler:** Exponential-backoff probe of halted actors via `is_due()`/`record_result()` in Phase 3g.

## Decision Pipeline Stages (`DEFAULT_STAGES` order)

| Stage | Effect |
|-------|--------|
| First-cycle suppression | Suppress trading on cold-start cycle 1 |
| Bar-jump suppression | Suppress 60min if bar count changed >100 (data-source switch) |
| Store prediction metadata | Record pre-decision signal state |
| Update MAE/MFE | Update max adverse/favorable excursion |
| Resolve signal | Map proba to BUY/SELL/FLAT via FixedThresholdStrategy(0.45) |
| Risk-off suppression | Flat AUDUSD when VIX>0 & SPX<0 |
| Sell-only filter | Override BUY→FLAT for `SELL_ONLY_ASSETS` (8 assets) |
| Spread gate | Block entry if spread > per-class threshold (observe 720 cycles first) |
| Confidence gate | Abort if net confidence below threshold |
| Signal stability filter | Require >0.65 max(prob_long, prob_short) to proceed |
| Signal hysteresis | 2-of-3 agreement required before flip |
| Meta-label advisory | Record meta-label recommendation (no enforcement) |
| Update regime bar counter | Track bars since last regime shift |
| Conviction gate | Flip gate based on regime conviction |
| Kelly sizing (P2) | Apply fractional Kelly multiplier from calibrated probability and tp/sl |
| Profit lock gate | Block flip if unrealized PnL > threshold |
| Manage position | Close/re-open with entry gate check |
| Build entry artifacts | Construct TradeDecision for execution |
| Route execution policy | Direct to PaperBroker or MT5Broker |
| Poll deferred entries | Execute pending deferred orders |

## Position Sizing Guardrails

Applied multiplicatively in entry sizing:
1. Drawdown taper — linear 1.0→min between start_dd/end_dd
2. Per-position cap — clip to max_position_pct_of_equity
3. Risk-per-trade cap — clip or skip if SL risk exceeds max_risk_per_trade_pct
4. Leverage budget — atomic lock from max_leverage × equity pool
5. Backstop multiplier — ratchet down on breach, 0.9 decay/cycle

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
- **Human review step**: Narrative lands as `narrative_pending.json`; must be confirmed via dashboard **NARR PENDING** button or auto-confirms at Monday noon (`auto_confirm_deadline_hour: 12`)
- **Staleness**: ≥7 days since week_start → stale flag suppresses governance, shown as `(STALE)` on dashboard
- **Failure mode**: scrape/LLM error → narrative carries forward with `fetch_error` status; dashboard shows yellow **NARR ERR** badge
- **Integration**: `_narrative_sl_mult` multiplied into SL in `_open_position`; `_narrative_size_scalar` applied in `_sizing_config` and execution bridge notional; `narrative_ok` flag in `check_halt_conditions` with -0.10 validity penalty
- **State storage**: `data/live/narrative_active.json`, `narrative_pending.json`
- **Config**: `configs/paper_trading.yaml` → `narrative_config` section
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
- **Config**: `configs/paper_trading.yaml` → `liquidity_config` section with threshold and pct params

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
- **Dashboard**: `PSIDriftCard.tsx` — per-asset table with color-coded feature rows, trend arrows, classification badges, worst-classification summary, collapsible halted section
- **Endpoint**: `GET /psi.json` (30s cache)

## Multiplicative Governance Chain

The SL layers stack multiplicatively on the existing SL chain:

```
final_sl_mult = base_sl_mult × regime_geom_sl × narrative_sl_mult × liquidity_sl_mult
final_size_scalar = min(narrative_size_scalar × liquidity_size_scalar, 0.30)
```

Validity penalties (feature stability + PSI drift) are additive and feed into the validity state machine, NOT into the SL/size chain:

```
validity_score = 0.80 − drawdown_penalty − pf_penalty − drought_penalty − drift_penalty − narrative_penalty − liquidity_penalty + stability_penalty + psi_penalty
```

Each layer is independently configurable, independently gated (by confidence, staleness, or threshold), and independently observable in the dashboard.
