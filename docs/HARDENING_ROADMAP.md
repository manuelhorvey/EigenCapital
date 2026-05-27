# Three-Tier Hardening Roadmap

Operational reference for cross-asset isolation, execution physics, extended history, lead-lag features, adaptive macro weighting, and portfolio-level circuit breaker.

All tiers have been implemented, validated, and merged to `main`. 845 tests pass across 30+ test files (includes Phases 0–6).

---

## Phases 0–6: Execution Research Framework

Transforms QuantForge from a prediction-driven system into a policy-driven execution research framework with causal attribution.

### Phase 0 — Frozen Kernel + Labels

Retrained labels with runtime-consistent initial geometry. Stateless `compute_initial_barriers()` ensures no adaptive logic leaks into labels. Training label geometry now matches runtime initial barriers — fixing the root cause of signal corruption.

**Files:** `labels/triple_barrier.py`, `labels/label_architectures.py`
**Tests:** Existing label tests pass with updated barrier alignment.

### Phase 1 — Entry Quality Engine

- `paper_trading/entry_optimizer.py` — `EntryOptimizer` maps (archetype, MarketStructureState) to `EntryAction` (ENTER / DEFER / SKIP)
- `paper_trading/deferred_entry.py` — `DeferredEntry` with idempotent `entry_id` from hash(signal_snapshot + symbol + timestamp_bucket)
- `paper_trading/decision.py` — `EntryAction` routing; `PolicyDecision`, `TPGeometry` as frozen dataclasses

**Tests:** `tests/test_deferred_entry.py`, `tests/test_entry_optimizer.py`

### Phase 2 — TP/Exit Geometry

- `paper_trading/tp_compiler.py` — Regime×archetype TP compiler with backloaded scale-out tiers per archetype
- Vol-expansion TP adjustment and inverted regime TP multipliers (trend/volatile get wider TP to let winners run; calm/range get tighter TP to clip mean reversion)
- Scale-out profiles: breakout 10/20/30/40, trend_pullback 15/20/30/35, mean_reversion 33/33/34, vol_expansion 10/15/25/50, momentum_ignition 10/10/30/50

**Files:** `paper_trading/tp_compiler.py`, `paper_trading/scale_out.py`
**Tests:** `tests/test_scale_out.py` (44 tests), `tests/test_tp_compiler.py`

### Phase 3 — Archetype Classification

- `features/archetypes.py` — 5 pure-feature archetypes computed from feature vector without model inference:
  - BREAKOUT: KER + ADX + volatility contraction
  - TREND_PULLBACK: Trend direction + retracement depth + volume
  - MEAN_REVERSION: Overextended Bollinger + RSI extremes
  - VOLATILITY_EXPANSION: Vol z-score spike + compression release
  - MOMENTUM_IGNITION: Rate of change acceleration + volume confirmation

**Tests:** `tests/test_archetypes.py`

### Phase 4 — Execution Policy Layer

- `paper_trading/execution_policy.py` — Archetype-to-policy dispatch via `POLICY_MAP`; `BasePolicy`, `ArchetypePolicy` mixins
- `PolicyDecision` as immutable instruction packet — decision layer ≠ state mutation layer
- Enforces: policy return is always `PolicyDecision`, not `PositionIntent`

**Tests:** `tests/test_execution_policy.py`

### Phase 5 — Fill Realism Layer

Seeded deterministic market physics emulation. Sits AFTER PolicyDecision freeze. Only degrades outcomes, never improves them.

- `paper_trading/execution_simulator.py` — Orchestrator: `simulate()`, `simulate_entry()`, `simulate_stop_loss()`, `simulate_take_profit()`
- `paper_trading/slippage_model.py` — Asymmetric slippage: SL 1.5× base + seeded noise (adverse); TP 0.1× base (neutral)
- `paper_trading/fill_model.py` — Gap-through detection (fills at gap-open if price gaps through stop); partial fill degradation (min_fill_prob 0.60)
- `paper_trading/latency_model.py` — Seeded bar-level execution delay (0–3 bars, gamma-distributed)
- `paper_trading/execution_bridge.py` — Integration point: `fill_price()` wraps entry via simulator; `fill_stop_loss()` / `fill_take_profit()` return `FillResult`
- Opt-in via `use_execution_simulator` flag — existing code path unchanged (wrap-first, replace-later)

**Key invariants:**
- All randomness seeded: SlippageModel(seed), FillModel(seed+1), LatencyModel(seed+2)
- Same seed + same inputs → identical FillResult
- Gap-through always fills at worst of open or trigger price
- Partial fill never exceeds requested qty
- Phase 5 modules import no strategy modules (xgboost, sklearn, meta_label)

**Tests:** `tests/test_phase5_fill_realism.py` (24 invariant tests)

### Phase 6 — Trade Attribution Analytics

Observe everything, mutate nothing. Never feeds back into labels, frozen kernel, or policies.

- `paper_trading/trade_attribution.py` — 4-domain causal attribution split:
  1. **PredictionAttribution** — Directional correctness, confidence calibration, regime alignment
  2. **ExecutionAttribution** — Entry timing quality, slippage impact, fill efficiency, counterfactuals
  3. **ExitAttribution** — MAE/MFE time-normalized, exit reason decomposition, scale-out efficiency
  4. **FrictionAttribution** — Spread cost, market impact, latency cost, total friction
- `AttributionCollector` — Observe-only collector wired into AssetEngine open/close lifecycle
- Counterfactual metrics (what-if: perfect entry, zero slippage, ideal exit vs actual)
- Archetype drift tracking, decision quality scoring, version hashing
- Never mutates labels, frozen kernel, or policies

**Tests:** `tests/test_phase6_attribution.py` (36 tests across 9 classes)

---

## Tier 1 — Cross-asset leakage and regime sizing

### Feature isolation

- `features/contract.py` — `validate_no_cross_asset_leakage()` ensures columns belong to the asset `contract_prefix`, allowed macro columns, `custom_features`, or shared prefixes (`macro_`, `spy_`, `regime_`).
- `features/registry.py` — `FEATURE_CONTRACT_VALIDATION = True`; each contract sets `contract_prefix` from the Yahoo ticker (e.g. `nzdjpy=x_mom_21`).
- `features/builder.py` — runs validation when the flag is enabled (after `build_features()`).
- `paper_trading/asset_engine.py` — validates after training and live inference feature builds.

**Tests:** `tests/test_feature_isolation.py`

### Regime-conditioned position sizing

- `shared/sizing.py` — `VolTargetSizing(regime_aware=True)` scales target vol: **range/calm × 1.2**, **volatile/crisis × 0.5**.
- `configs/paper_trading.yaml` — `regime_sizing: true` per live asset; `vol_baselines` floors realized vol in sizing.
- `paper_trading/portfolio_builder.py` — sets `vol_scalar: true`, `vol_baseline`, and `regime_sizing` on each asset config.

**Tests:** `tests/test_sizing.py`

### Portfolio-level drawdown circuit breaker

- `config_manager.py` — `portfolio_drawdown_limit: float = -0.15` in `EngineConfig`.
- `engine.py` — `portfolio_peak_value` tracks the portfolio's all-time-high (including satellite). In `run_once()`, after price refresh but before signal generation, if portfolio drawdown ≤ limit, all positions are force-closed with reason `portfolio_circuit_breaker`.
- Integrated with `_compute_portfolio_summary()` — `portfolio_drawdown` and `portfolio_peak_value` exposed in state snapshot.
- Config: `configs/paper_trading.yaml` → `portfolio_drawdown_limit: -0.15`.

### Trade quality gates

- `asset_engine.py` — `min_confidence` (default 50%) skips trade entry when model confidence is below threshold, preventing low-conviction flips.
- `asset_engine.py` — `max_holding_days` (default 30) time-stop force-closes positions held beyond N calendar days without hitting SL/TP.
- Both configured per-asset in `paper_trading.yaml` under `config:`:
  ```yaml
  config:
    min_confidence: 50
    max_holding_days: 30
  ```

---

## Tier 2 — Liquidity model and cost decay

### Shared execution config

- `shared/execution_config.py` — `ExecutionConfig`, `compute_slippage_cost()`, `compute_market_impact()`, `build_execution_configs()`.
- `research/risk/execution_physics.py` — imports the same types for survival simulation.

### Live paper fills

- `execution/paper_broker.py` — per-asset spread expansion from vol z-score; linear/square-root impact vs ADV.
- `paper_trading/execution_bridge.py` — slippage-aware fill prices for `AssetEngine` open/close (does not replace `PositionManager` state).
- `paper_trading/engine.py` — builds `execution_configs` from YAML and attaches `ExecutionBridge` to every `AssetEngine`.

### Config (`configs/paper_trading.yaml`)

```yaml
execution_defaults:
  base_spread_bps: 0.5
  spread_vol_slope: 2.0
  spread_max_bps: 50.0
  impact_model: square_root
  impact_coeff: 0.1
  avg_daily_volume: 1000000000

assets:
  NZDJPY:
    execution_config:
      base_spread_bps: 2.0
      avg_daily_volume: 300000000
```

Estimated impact (bps) is passed into sizing via `impact_bps` when `vol_scalar` is enabled; `edge_decay()` caps size at 50% above 5 bps impact.

**Tests:** `tests/test_paper_broker.py`, `tests/test_execution_physics.py`, `tests/test_execution_bridge.py`

---

## Tier 3 — Extended history, lead-lag, adaptive macro (✅ COMPLETE)

### 3A — Extended history

| Step | Command / artifact | Status |
|------|-------------------|--------|
| Download 2000+ OHLCV | `python data/loaders/backfill_to_2000.py` | ✅ 33 tickers from 2000-01-01 |
| Neutral prediction stubs | `python scripts/run_extended_history_pipeline.py` | ✅ |
| Extended survival sim | `python research/risk/survival_sim.py --extended-history --paths 5000` | ✅ Sharpe 6.26, 0% ruin |
| Export metrics | `data/research/survival_extended.json` | ✅ |
| Compare 5y vs 25y | `python diagnostics/extended_history_report.py` | ✅ |

**Results:** Extended-history survival (25y, 5000 paths): Full Governance Sharpe 6.26, Ann.Ret +25.1%, 0% ruin on all governance variants. Nearly identical to 10-year results (Sharpe 6.27) — confirms long-term tail robustness.

- `features/builder.py` — `compute_training_data_extended()` for full-history feature matrices.
- `research/risk/synthetic_stress.py` — `adjust_injection_rate_for_crisis_density()` lowers synthetic injection when empirical CRISIS density is already high.

**Tests:** `tests/test_synthetic_stress_extended.py`

### 3B — Lead-lag

| Step | Command / artifact | Status |
|------|-------------------|--------|
| Full matrix + heatmap | `python research/lead_lag/run_lead_lag.py` | ✅ 205 significant relationships across 32 assets |
| Matrix parquet | `data/research/lead_lag_results.parquet` | ✅ |
| Heatmap PNG | `data/research/lead_lag_matrix.png` | ✅ |
| Curated edges | `data/research/lead_lag_edges.yaml` | ✅ 9 edges (1 pre-existing + 8 new DJI/GC) |

**Results:**
- **DJI leads FX crosses** at lag=1: AUDJPY (+0.46), NZDJPY (+0.42), CADJPY (+0.39), GBPJPY (+0.33), EURAUD (–0.37), USDCAD (–0.39). All p-values < 1e-60.
- **GC leads USDJPY/USDCHF** at lag=1 with corr –0.34 (p < 1e-60).
- 8 new lead-lag features wired into production: `dji_lead_1` on EURAUD, NZDJPY, CADJPY, AUDJPY, USDCAD, GBPJPY; `gc_lead_1` on USDJPY, USDCHF.

- `features/lead_lag_features.py` — loads edges; `features/builder.py` attaches columns listed in `custom_features`.
- `features/builder.py` — `_attach_lead_lag_features()` with `_normalize()` + `_resolve_leader_path()` (yfinance fallback).
- `features/pair_specific.py` — `build_lead_lag_features()` for shift-based alignment.
- Lead-lag edge: **AUDJPY** uses `nzdjpy_lead_3` and `dji_lead_1` — registered in `features/registry.py`.

**Tests:** `tests/test_lead_lag_heatmap.py`

### 3C — Adaptive macro weight

- `models/macro_expert_head.py` — `online_weight=True` tracks rolling 63d Sharpe; soft-updates blend weight in **[0.25, 0.65]**.
- `configs/paper_trading.yaml` — `adaptive_macro: true` on **NZDJPY** (requires a model pickle with `macro_head`, e.g. `HybridRegimeEnsemble`).
- `paper_trading/asset_engine.py` — directional macro vs blend feedback on trade close; `macro_weight` exposed on decision JSON.
- ADR-022 documents the design and validation.

**ADR:** [ADR-022](adr/ADR-022-macro-adaptive-weight.md)  
**Tests:** `tests/test_macro_adaptivity.py`, `tests/test_macro_trade_feedback.py`

---

## Quick validation

```bash
pytest tests/ -q --tb=short
```

---

## Remaining operational work

1. ~~Synthetic stress hardening~~ (complete — validated circuit breaker + trade quality gates reduce synthetic ruin)
2. ~~Deploy hybrid ensemble pickles~~ (complete — adaptive_macro active on NZDJPY)

---

## Tier 4 — Dynamic SL/TP Calibration and Dashboard Monitoring

### 4A — Scale-out integration and trailing stop

- `paper_trading/scale_out.py` — `ScaleOutEngine` emits `trailing_activated` signal when `trailing_after_tier` (configurable tier index) fills.
- `paper_trading/dynamic_sltp.py` — `DynamicSLTPEngine` tracks cross-bar best price via `_best_price_seen` and `reset_best_price()` for trailing stop computation.
- `paper_trading/asset_engine.py` — Stops `_initial_sl`/`_initial_tp` at entry for accurate trailing; wires trailing activation to scale-out fills.
- `tests/test_dynamic_sltp.py` — 51+ tests for barriers, calibrate, trailing stop, post-entry adjustment, helpers, confidence-based SL adjustment, best-price tracking.
- `tests/test_scale_out.py` — 35 tests for config building, plan building, tier checks, breakeven activation, trailing activation.

### 4B — Probability-based SL/TP via meta-label confidence

- `paper_trading/dynamic_sltp.py` — `confidence_sl_adjust` config parameter (default 0.0, disabled); `_confidence_sl_factor()` computes dynamic SL tightness from meta-confidence (p=0.5 → 1.0×, p=0.9 → 1.0 - adjust, p=0.1 → 1.0 + adjust/2).
- `paper_trading/asset_engine.py` — `compute_barriers()` accepts `meta_confidence` param; threads `_last_meta_proba` through for live inference.
- Strength: preserves meta-label gating (ENTER/BLOCK) while biasing SL width toward confidence.

### 4C — Shadow SL/TP analytics

- `paper_trading/tracer.py` — `shadow_compare_sltp()` logs runtime SL/TP deviations from original label barriers in bps.
- `paper_trading/shadow_memory.py` — `build_baseline()` tracks SL/TP drift history (mean/max delta, adjustment count).
- `paper_trading/diagnostics.py` — `build_shadow_report()` accepts `sltp_drift` field for diagnostics output.
- `paper_trading/asset_engine.py` — Wired into trailing stop activation and post-entry adjustment paths.

### 4D — Dashboard polish

- `paper_trading/asset_engine.py` — Snapshot includes `scale_out_tiers` (fraction, price, filled, fill_price per tier).
- `paper_trading/dashboard/src/components/ui/SltpGauge.tsx` — Color-coded gauge bars for TP/SL/Flip rates (GREEN/YELLOW/RED thresholds).
- `paper_trading/dashboard/src/components/TradeOutcomes.tsx` — Gauge column in per-asset trade outcomes table.
- `paper_trading/dashboard/src/components/AssetCard.tsx` — Scale-out tier progress bar when a position has active scale-out tiers.

---

## Tier 5 — Macro Narrative Governance (Weekly LLM Overlay)

### Objective

Add a weekly macro context layer that adjusts SL width and position sizing based on LLM-extracted narrative signals from FXStreet analysis. This is an execution governance overlay, not a feature — it shapes how the system executes, not what it predicts.

### Implementation

#### Pipeline

- `features/fxstreet_fetcher.py` — `fetch_fxstreet_article()` scrapes FXStreet "Week ahead" article; `call_llm()` sends text to Claude API with structured JSON prompt; `run_weekly_narrative_pipeline()` orchestrates fetch → LLM → pending; `confirm_pending_narrative()` promotes pending to active; `get_narrative_status()` returns combined state.
- `features/macro_narrative.py` — `MacroNarrativeFeatures` dataclass with: `geopol_risk_score`, `fed_hawkishness`, `rbnz_hawkishness`, `rba_hawkishness`, `boj_intervention_risk`, `energy_crisis_pressure`, currency biases, `overall_regime`, `confidence`; `narrative_governance_scalars()` maps features to `{sl_mult, size_scalar}`.
- `paper_trading/asset_engine.py` — `_load_narrative_state()` on init, `set_narrative_state()` for runtime updates; `_narrative_sl_mult` multiplied into SL in `_open_position`; `_narrative_size_scalar` applied in `_sizing_config` and execution bridge notional; `narrative_ok` flag in `check_halt_conditions` with -0.10 validity penalty.
- `paper_trading/engine.py` — `_init_narrative()`, `_refresh_narrative()` in Phase 3.5 of `run_once()`: runs pipeline on Monday before noon (pending) or auto-confirms after deadline_hour; carries forward with staleness on failure.

#### Human Review Step

- Pending narrative saved as `data/live/narrative_pending.json`
- Dashboard renders **NARR PENDING** button (one-click confirm via `POST /narrative/confirm`)
- Auto-confirm at `auto_confirm_deadline_hour` ET (default 12:00)
- Scrape/LLM errors surface as yellow **NARR ERR** badge — narrative carries forward

#### Dashboard

- `paper_trading/dashboard/src/hooks/useNarrative.ts` — React Query hook polling every 30s
- `paper_trading/dashboard/src/components/Header.tsx` — NARR PENDING button, regime badge (color-coded), stale indicator, NARR ERR badge

#### Config

```yaml
narrative_config:
  enabled: true
  fxstreet_url: "https://www.fxstreet.com/analysis"
  geopol_sl_widen_pct: 10
  risk_off_size_reduce_pct: 20
  min_confidence: 0.6
  auto_confirm_deadline_hour: 12
```

**Tests:** TBD (manual verification during first Monday cycle)

---

## Tier 6 — Liquidity Regime Model (Per-Tick Proxy)

### Objective

Detect abnormal liquidity conditions from daily OHLCV data alone (no tick/order book required) and adjust execution parameters accordingly.

### Implementation

#### Core

- `features/liquidity_regime.py`:
  - `compute_liquidity_features(df)`: Volume z-score (rolling 21d), Amihud illiquidity ratio z-score (`|return| / volume × close`), Corwin-Schultz bid-ask spread estimate from daily high/low.
  - `classify_liquidity_regime(features)`: Returns NORMAL / THIN / STRESSED based on configurable thresholds.
  - `liquidity_governance_scalars(regime)`: Returns `{sl_mult, size_scalar, halted}`.

#### Governance Rules

| Regime | SL Adjustment | Size Adjustment | Halts? |
|--------|--------------|-----------------|--------|
| NORMAL | 1.0× | 1.0× | No |
| THIN | +15% (1.15×) | −15% (0.85×) | No |
| STRESSED | +30% (1.30×) | −30% (0.70×) | Yes |

#### Integration

- `paper_trading/asset_engine.py` — `_load_liquidity_state()` on init; `_refresh_liquidity()` called every signal cycle; `_liquidity_sl_mult` in SL chain; `_liquidity_size_scalar` in sizing notional; `liquidity_ok` flag halts on STRESSED with -0.10 validity penalty.
- `paper_trading/engine.py` — liquidity regime exposed per-asset in `get_state()`.
- `paper_trading/serve.py` — `GET /liquidity.json` with 30s cache.
- `paper_trading/dashboard/src/hooks/useLiquidity.ts` — React Query hook polling every 30s.
- `paper_trading/dashboard/src/components/Header.tsx` — LIQ THIN (yellow) / LIQ STRSD (red) badge with per-asset hover tooltip.

#### Config

```yaml
liquidity_config:
  enabled: true
  regime_window: 21
  volume_z_thin_threshold: -1.5
  volume_z_stressed_threshold: -2.5
  amihud_high_threshold: 1.5
  amihud_stressed_threshold: 3.0
  thin_sl_widen_pct: 15
  thin_size_reduce_pct: 15
  stressed_sl_widen_pct: 30
  stressed_size_reduce_pct: 30
  stressed_halt: true
```

**Tests:** TBD (requires OHLCV data fixture for feature computation validation)

---

## Tier 7 — PSI Drift Monitoring (Automated Distribution Shift Detection)

### Objective

Automate manual PSI drift checks from the runbook into a per-cycle governance layer that detects feature distribution shifts and applies validity penalties before they degrade execution.

### Implementation

#### Core

- `monitoring/psi_monitor.py`:
  - `compute_psi(expected, actual, bins=10)`: Fixed-width bins from baseline min/max, first/last bin extended to ±inf for overflow. Returns 0.0 if distributions are identical or samples insufficient.
  - `classify_drift(psi)`: Returns NO_DRIFT (< 0.1), MODERATE (0.1 – 0.2), or SEVERE (> 0.2).
  - `PSIDriftEntry` dataclass: per-feature PSI score, classification, trend (STABLE / INCREASING / DECREASING vs previous cycle), importance score.
  - `PSISnapshot` dataclass: per-asset snapshot with per-feature list, worst_classification, moderate_count, severe_count, psi_ok flag, penalty.

#### Baseline Population

- Persisted as `data/live/psi_baseline/{asset}.parquet` — full training feature matrix
- Written immediately after `model.fit()` in `asset_engine.train()`, before any post-processing
- Only updated when a new walk-forward window promotes (annual retrain)

#### Per-Cycle Computation

- In `_generate_and_apply()`, after feature build, rolling 21-day window from `features_df.tail(21)`
- Top-10 features per asset loaded from most recent `importance_store` snapshot
- Per-feature PSI computed against baseline fixed-width bins

#### Governance Rules

| Condition | Effect |
|-----------|--------|
| Any MODERATE feature | −0.08 validity penalty |
| Any SEVERE feature | −0.20 validity penalty (additive with MODERATE: max −0.28) |
| 3+ SEVERE features simultaneously | `psi_ok = False`, hard halt |

Penalties are additive with feature stability penalties (both sum in `update_validity()`).

#### Dashboard

- `paper_trading/dashboard/src/hooks/usePSI.ts` — React Query hook polling `/psi.json` every 30s
- `paper_trading/dashboard/src/components/PSIDriftCard.tsx` — per-asset table with feature rows, color-coded classification badges (green/amber/red), trend arrows (↑↓→), worst-classification summary, collapsible halted section with PSI HALT badge

#### Endpoint

- `GET /psi.json` (30s cache) — per-asset per-feature PSI scores, classification, trend, psi_ok status

**Tests:** `tests/test_psi_monitor.py` — 21 tests covering compute_psi (identical, shifted, insufficient samples, constant, NaN), classify_drift boundaries, trend, persist/load round-trip, compute_drift with no baseline, identical, shifted, and missing features, penalty values, && psi_ok at 2 vs 3 severe thresholds

---

## Multiplicative Governance Chain

The SL/size layers stack multiplicatively:

```
final_sl_mult = base_sl_mult × regime_geometry_sl × narrative_sl_mult × liquidity_sl_mult
final_size_scalar = base_size × narrative_size_scalar × liquidity_size_scalar
halt = drawdown_halt OR pf_halt OR drought_halt OR drift_halt OR narrative_halt OR liquidity_halt OR psi_halt
```

Validity penalties (feature stability + PSI drift) are additive, not multiplicative, feeding into the validity state machine:

```
validity_score = 0.80 − drawdown_penalty − pf_penalty − drought_penalty − drift_penalty − narrative_penalty − liquidity_penalty + stability_penalty + psi_penalty
```

Each layer is independently configurable, independently gated (by confidence, staleness, or threshold), and independently observable in the dashboard.

---

## Tier 8 — Dashboard Operations Hardening (rc.6)

### Objective

Harden the React dashboard against silent failures, re-render cascades, stale data, and poor UX during edge cases (loading, error, empty, closed-market).

### Implementation

#### Runtime Type Safety

- `paper_trading/dashboard/src/lib/schemas.ts` — Zod schemas for all 8 API endpoints (`PortfolioStateSchema`, `NarrativeStateSchema`, `LiquidityStateSchema`, `PSIStateSchema`, `GovernanceStateSchema`, `GovernanceHistorySchema`, `RiskParityDataSchema`, `ClosedTradesSchema`). Every hook uses `.safeParse()` on fetch response — invalid server shapes surface as logged errors + user-visible fallback, not silent NaN/undefined.
- `paper_trading/dashboard/src/App.tsx` — Each major panel wrapped in a per-component `<ErrorBoundary>` with panel-style `<PanelFallback>` component (title + description + icon). One bad endpoint no longer takes down the entire dashboard.

#### Re-render Prevention

- `paper_trading/dashboard/src/hooks/useMarketClosed.ts` — Changed from `usePortfolioState()` subscription (re-renders on every state.json poll) to `useQueryClient.getQueryData()` selector pattern. Reads cached data without subscribing to the query observer.
- `paper_trading/dashboard/src/hooks/usePortfolioState.ts` — Added `retry: false`, top-level shape check in queryFn.

#### Cache Strategy

| Endpoint | staleTime | Notes |
|----------|-----------|-------|
| `narrative.json` | 300s | Weekly data, no need for fast polls |
| `psi.json` | 60s | Drift changes slowly |
| `liquidity.json` | 60s | Regime is stable intraday |
| `governance.json` | 25s | Only affects visual badges |
| `state.json` | 0 | Default — portfolio updates every cycle |
| `closed_trades.json` | 40s | Changes only on exit |
| `risk_parity.json` | 60s | Rebalance is rare |
| `governance_history.json` | 300s | Historical, append-only |

Global: `refetchOnWindowFocus: true`, `gcTime: 300_000`.

#### New Dashboard Components

- `paper_trading/dashboard/src/components/ConnectionStatus.tsx` — Header bar monitoring 5 endpoints (`/ping`, `/state.json`, `/narrative.json`, `/governance.json`, `/risk_parity.json`). Shows **Live** (green, all 5 OK), **Degraded** (yellow, 1–2 failing), **Offline** (red, 3+ failing). Hover tooltip lists per-endpoint status.
- `paper_trading/dashboard/src/components/AlertFeed.tsx` — Captures governance halt/state-change events and PSI-SEVERE events from real-time query data. Persisted in `sessionStorage`. Each alert is dismissible. Shows event type, asset, timestamp, severity badge.
- `paper_trading/dashboard/src/components/ui/PanelFallback.tsx` — Reusable error fallback with icon, title, description. Used by all per-component ErrorBoundaries.
- `paper_trading/dashboard/src/components/sections/AnchorNav.tsx` — Sticky horizontal nav below header (Portfolio / Signals / Trades / Governance / Risk / Charts). Uses `IntersectionObserver` to track which section is active. Click scrolls to section.
- `paper_trading/dashboard/src/components/ui/DataTable.tsx` — Sort persistence changed from `localStorage` to `sessionStorage` (per-tab sort state, not persistent across sessions).
- `paper_trading/dashboard/src/components/GovernanceStateCards.tsx` — Per-asset governance summary cards. Red 3px left-border on halted assets. Validity state badge (GREEN/YELLOW/RED/INIT). Tooltips on FLOOR/HALTED status text.
- `paper_trading/dashboard/src/components/RiskParityPanel.tsx` — Bar chart of risk parity allocations. Bars colored by governance state (RED/YELLOW/GREEN). Equal-weight reference line. Total allocation footer.

#### Safe Formatting Utilities

- `paper_trading/dashboard/src/utils/format.ts` — `safeToFixed(val, digits)` returns `"—"` for null/NaN/Infinity; `formatHeldDuration(seconds)` returns `"3d 4h"` or `"45m"`; `formatTimeAgo(isoString)` returns relative time; `formatPct(val)` returns signed percentage.

#### Skeleton & Error States

Components that previously returned `null` while loading now show skeleton loaders: `GovernanceStateCards`, `PSIDriftCard`, `RiskParityPanel`, `GovernancePanel`.

#### Governance Colors Aligned to Spec

- `paper_trading/dashboard/src/index.css` — `--color-gov-green: #22c55e`, `--color-gov-yellow: #eab308`, `--color-gov-red: #ef4444`.
- `paper_trading/dashboard/tailwind.config.js` — `gov-green`, `gov-yellow`, `gov-red` mapped to same hex values.
