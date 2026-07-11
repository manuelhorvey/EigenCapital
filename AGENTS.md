# EigenCapital — Agent Operating Guide

## Production Trade Lifecycle Audit (2026-07-02)

**Save**: `data/processed/full_audit_results.json` (15 phases, 11 recommendations)

```
[ALPHA] (score=0.510) Deploy exit strategy: trail_33pct
        Sharpe 0.06→0.50, total_R=+3587.1, max_dd=-23.5R (6.9× baseline)
[INFO ] (score=0.510) Filters saved 66.4R (net beneficial)
[ALPHA] (score=0.440) Optimal holding period: 200 candles (Sharpe 0.09 vs 0.06)
        **REJECTED 2026-07-05** — simple sweep (not WF), Sharpe +0.02, max_dd 10× worse (-1,762R). Not safe to deploy.
[ALPHA] (score=0.412) Deploy per-asset exit strategies (15 assets)
[SIGMA] (score=0.403) Reduce max concurrent positions (16)
[SIGMA] (score=0.393) High risk of ruin (p95 DD=39.1%)
[SIGMA] (score=0.378) 6 assets with poor session performance
[INFO ] (score=0.375) 390 correlated entry clusters found
[ALPHA] (score=0.362) 11 assets need individual holding periods
[SIGMA] (score=0.351) Only 36% of entries are trend-aligned
[SIGMA] (score=0.333) Regime transitions degrade performance (56% assets worse)
```

**Run**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/production_audit.py --output data/processed/full_audit_results.json`

**Architecture**: `scripts/analysis/audit_phases/` — 16 phase modules + orchestrator. Phase 0 (`phase_data.py`) augments trades with temporal metadata and defines shared constants. Phases 1–17 are independent forensics. Phase 18 aggregates and scores.

**Fixed 2026-07-02**: Phase 6 now reconstructs price paths from OHLCV map (was silently returning original R for all holding periods); Phase 14 detects bull↔bear transitions instead of relying on `c == MA50` (which never fires in trending markets).

## Project Identity

Cross-sectional multi-asset paper trading engine. 22-asset portfolio (21 FX/commodities/indices + BTCUSD) with per-asset XGBoost models, regime-conditional ensemble (disabled 2026-06-20), 17-layer governance (core) + 3 adaptive budget layers + decision pipeline + position sizing guardrails, adaptive exit engine, and MT5 bridge execution (Exness demo via Wine).

**2026-06-20: AUDNZD, EURUSD, AUDCHF removed from trading.** These 3 assets accounted for the model's confirmed directional instability failure mode (confident wrong-direction bets during trends). Removed from the domain config (`configs/domains/assets/`), mt5_symbol_map, shadow analytics, and risk-off suppression lists. 22-3=19 remaining assets (subsequent additions grew to 21; see timeline below). See the Walk-Forward PnL Backtest section for the full diagnostic chain.

**2026-06-20 (late): GBPNZD removed from trading; USDCAD/NZDUSD allocation halved.** GBPNZD had tp/sl=1.0/3.0 (ratio 0.33), requiring 75% breakeven WR. Model achieved 72.3% — close but net-negative (-37R, -71R max_dd). USDCAD and NZDUSD reduced from 5% to 2.5% allocation to limit their drawdown impact while keeping diversification. 19-1=18 remaining assets.

**2026-06-22: GBPUSD promoted to portfolio.** Walk-forward shows IC 0.186 (4/4 folds positive), HR 0.371. Feature registry pt_sl=(1.97, 0.52) gives favorable R:R=3.79. Added to `configs/domains/assets/` and `configs/mt5_symbol_map.yaml`. 18+1=19 assets.

**2026-06-23: AUDUSD, EURNZD, NZDUSD removed from SELL_ONLY filter.** Corrected walk-forward methodology shows BUY WR > 50% for all three (AUDUSD 64.5%, EURNZD 57.6%, NZDUSD 57.7%) — BUY is no longer inverted. The original SELL_ONLY diagnosis was based on a broken walk-forward (no purging, EWM labels, validation-split early stopping). The filter no longer trades BUY on the remaining 3 assets (CADCHF, NZDCHF, EURAUD) where BUY WR remains 11-31%. ^DJI, USDCHF, EURCHF removed from SELL_ONLY 2026-06-26 after trend-exhaustion features improved BuyWR above breakeven. ES, NQ removed from SELL_ONLY 2026-07-01 after portfolio remediation.

**2026-06-25: Structural asymmetry confirmed — SELL_ONLY is permanent under current feature design.** Three independent experiments prove BUY direction is not recoverable for the original 8 flagged assets: (1) threshold scan 0.01-0.99 — no threshold produces BUY WR > 50%; (2) rolling 252 window — p_long mean shifts 0.4→0.6 in wrong direction (more BUY, worse accuracy); (3) label inversion (y' = 1-y training) — EURAUD BUY WR only improves 22.7%→31.0%. The feature space encodes SELL predictability (62-90% WR) but not BUY predictability (0-32% WR). This is a portfolio-wide issue, not subset-specific — non-SELL_ONLY assets average only 49.3% BUY WR. The architecture is a **pure SELL alpha engine** for these 8 assets; BUY restoration is closed under current feature/label design. See `scripts/restoration/` for the diagnostic framework, gatekeeper, and architecture document.<br>**Updated 2026-07-11:** SELL_ONLY expanded to 6 permanent assets (CADCHF, EURAUD, EURCHF, GBPCHF, GBPJPY, NZDCHF). EURCHF, GBPCHF, GBPJPY added after additional walk-forward analysis confirmed BUY inversion is irrecoverable under current feature design.

**2026-07-11: Direction-conditional thresholds deployed.** Global defaults: `min_confidence_buy=45` (unlocks marginal BUY trades), `min_confidence_sell=55` (maintains SELL discipline). Per-asset BUY overrides at 40% for 5 assets (AUDJPY, EURCHF, GBPCHF, GBPJPY, GC) where threshold sweep showed net PnL improvement. DirectionalCalibrator (Platt base, ECE 0.0178) trained on retrained narr walk-forward parquets. Total backtest result: +838.06 R (Sharpe 58.47), +313.60 R improvement over no-gate baseline.

## Architecture Quick Reference

- **Models**: Per-asset XGBClassifier (base only) — regime-conditional ensemble disabled 2026-06-20 (walk-forward p=0.83; see ADR-026)
- **Features**: 40 alpha columns per asset (9 core + 6 trend-exhaustion + 2+ COT z/change + 4 cross-asset + 10 directional momentum/carry splits + 15 FXStreet narrative cross-asset features; plus up to 16 additional COT pair columns from all covered CFTC pairs) + 7 regime (hurst, kaufman_er, adx, vol_zscore, compression, utc_hour, session_vol_profile). See `docs/FEATURES.md` for canonical taxonomy.
- **Labels**: Triple-barrier with per-asset pt_sl, vertical_barrier=20, gap >= vb
- **Config**: `configs/paper_config_registry.py` + `configs/domains/` — domain-first config tree promoted in Phase 12; mode overrides, global defaults, per-asset config
- **Portfolio Maturity Framework (5-layer, P0–P4)**: P0 weights (`shared/portfolio_weights.py`), P1 calibration (`shared/calibration/`), P2 Kelly (`shared/kelly.py`), P3 factor model (`shared/factor_model.py`), P4 HRP (`portfolio/hrp_allocator.py`). All config-gated.
- **PEK (Portfolio Execution Kernel)**: `PortfolioStateSnapshot` (built pre-phase) + `RiskEngineV2` (adaptive budget) + `PerformanceState` (velocity + outcome telemetry) + `PortfolioAdmissionController` (two-stage filter → rank → enforce)
- **Inference**: `paper_trading/inference/pipeline.py` → base model → calibration (P1) → governance → execute (ensemble disabled)
- **Training**: `paper_trading/inference/training.py` — base model only, scale_pos_weight, meta-labeling. Expanding-window.
- **Entry gates**: `entry_service.py` price deviation check; profit lock in `manage_position` (blocks flips when PnL > profit_lock_threshold_pct); **PEK budget enforcement** (closes lowest-ranked if portfolio notional exceeds max)
- **Position sizing guardrails**: drawdown taper → per-position equity cap → risk-per-trade cap → min viable gate (leverage budget removed — replaced by PEK central admission)
- **Independent MT5 sizing**: Paper from $100K mtm_value; MT5 from broker balance via `_compute_mt5_qty()`
- **Orchestrator**: `EngineOrchestrator` (ThreadPoolExecutor, 8 workers), **5-phase cycle**: PRE (PEK state) → 1a (signal) → 1b (admission) → 2 (validity) → 3 (health) → 4 (persist) with MT5 orphan sub-phases (A-D)

```
             ┌───────────────────────────────────────────┐
             │ PRE: PortfolioStateSnapshot               │
             │ RiskBudget + PerformanceState             │
             │ RiskEngineV2 adaptive budget              │
             └─────────────┬─────────────────────────────┘
                           │
             ┌─────────────▼─────────────────────────────┐
             │ Phase 1a: REFRESH                         │
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
           │ halt       │      │
           │ Recovery-  │      │
           │ Scheduler  │      │
           └────────────┘      │
                               ▼
                 ┌───────────────────────────────┐
                 │ Factor Exposures (10 groups)  │
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
                 │ Net-short skew check          │
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

- **Governance**: 17 core layers + 3 adaptive budget layers (RiskEngineV2, PEK admission, PerformanceState velocity) + HealthMonitor + VaR/CVaR + RecoveryScheduler + 22-stage decision pipeline + position sizing guardrails
- **MT5 Bridge**: `paper_trading/ops/mt5_client.py` — TCP frame protocol to Wine-hosted MT5 (port 9879)
- **Dashboard**: React SPA on port 5000, state via `state.json`

## Key Files

| File | Purpose |
|------|---------|
| `configs/paper_config_registry.py` + `configs/domains/` | Domain-first config tree (capital, assets, SL/TP, sizing, exits, halt, MT5, governance, ML, alerting, …) |
| `shared/portfolio_weights.py` | P0 portfolio truth layer — 4 weight strategies, decorator pattern, pure functions |
| `shared/calibration/` | P1 calibration layer — `BinnedCalibrator`, `CalibrationRegistry`, `ECETracker` |
| `shared/kelly.py` | P2 fractional Kelly sizing — `compute_kelly_fraction`, `compute_kelly_multiplier` |
| `paper_trading/pek/contracts/portfolio_state.py` | Immutable `PortfolioStateSnapshot` — single source of truth for portfolio exposure |
| `paper_trading/pek/contracts/performance_state.py` | Immutable `PerformanceState` with `RegimeVelocity` — system behavioral telemetry |
| `paper_trading/pek/contracts/risk_budget.py` | `RiskBudget` — adaptive risk limits consumed by PEK |
| `paper_trading/pek/state/portfolio_state_builder.py` | `PortfolioStateBuilder` — factory for `PortfolioStateSnapshot` |
| `paper_trading/pek/perf/performance_state_builder.py` | `PerformanceStateBuilder` — outcome tracker + velocity processor |
| `paper_trading/pek/engine_v2.py` | `RiskEngineV2` — adaptive budget from snapshot + performance state |
| `paper_trading/orchestrator/admission/controller.py` | `PortfolioAdmissionController` — PEK two-stage admission (filter → rank) |
| `paper_trading/orchestrator/admission/signal.py` | `AdmissionSignal` — immutable signal admission contract |
| `shared/factor_model.py` | P3 factor model — 10 factor groups, factor-constrained weight optimization |
| `portfolio/hrp_allocator.py` | P4 HRP fix — `_get_quasi_diag` with `optimal_leaf_ordering` |
| `paper_trading/engine.py` | `PaperTradingEngine` — main loop, capital sync, parallel orchestrator |
| `paper_trading/asset_engine.py` | `AssetEngine` — per-asset lifecycle, train(), generate_signal(), `_kelly_multiplier`, `_calibration_registry` |
| `paper_trading/inference/training.py` | `AssetTrainingPipeline` — base + regime model training |
| `paper_trading/inference/pipeline.py` | `AssetInferencePipeline` — live inference with calibration (P1) |
| `paper_trading/inference/regime_model.py` | `RegimeConditionalModel` — per-asset regime classifier |
| `paper_trading/inference/ensemble.py` | `EnsembleSignal` — 60/40 blend logic |
| `paper_trading/ops/monitor.py` | Main entry point — loads models, runs engine, serves dashboard |
| `paper_trading/execution/decision_pipeline.py` | Decision pipeline stages — includes `apply_kelly_sizing` (P2), profit lock gate |
| `paper_trading/services/entry_service.py` | Entry validation, full sizing chain (Kelly multiplier → drawdown taper → position cap → risk cap), price deviation gate |
| `paper_trading/services/engine_rebalance_service.py` | Live rebalance — reads `weight_method` from config, calls `compute_weights()` |
| `paper_trading/orchestrator/engine.py` | `EngineOrchestrator` — phases 1-4 (pre-phase PEK state, parallel signal, PEK admission, validity, portfolio health, persist) with MT5 orphan sub-phases (A-D) |
| `paper_trading/orchestrator/orphan_reconciliation.py` | `OrphanReconciler` — extracted MT5 orphan lifecycle (Phase A drain, Phase B stale tickets, Phase C report, Phase D adoption) |
| `paper_trading/orchestrator/health.py` | VaR/CVaR computation — `portfolio_vol_estimate()`, `compute_var_cvar()` pure functions |
| `paper_trading/orchestrator/correlation.py` | `CorrelationMonitor` — position concentration, portfolio cross-asset correlation |
| `paper_trading/execution/mt5_broker.py` | `MT5Broker` — MT5 execution with `current_mt5_drawdown_pct()` |
| `features/alpha_features.py` | Alpha feature builder (9 base + 6 trend-exhaustion + 2+ COT z/change + 4 cross-asset + 10 directional splits + 15 FXStreet narrative features + COT per covered pair) |
| `features/regime_features.py` | Regime feature builder (7 cols) |
| `features/data_fetch.py` | Data fetching with MT5/yfinance fallback |
| `features/labels.py` | Triple-barrier labeling + PurgedWalkForwardFolds |
| `LIVE_CONTRACT.md` | Immutable system contract (update when architecture changes) |
| `scripts/backtest/backtest_pnl.py` | PnL backtest from OOS signal parquets (R-multiples, autocorrelation-adj Sharpe, `--weight-method` option) |
| `scripts/backtest/compare_ensemble.py` | Ensemble vs base PnL comparison with per-fold sign test |
| `scripts/training/train_calibration.py` | Train calibrators from walk-forward signal parquets |
| `scripts/replay/replay_rebalance.py` | Reconstruct historical portfolio weights + compare with live |
| `paper_trading/governance/risk.py` | Risk evaluation, SL hit rate, drift scoring, **SELL tripwire** (per-asset deque, TP=1/SL=0, win, 20-trade window, 65% threshold, WARNING log on trip) |
| `paper_trading/services/engine_state_service.py` | Portfolio summary with `factor_exposures`, `position_concentration` |

## Position Sizing Chain

Paper positions are sized through multiplicative guardrails:

```
effective_cap = capital_base × min(mtm / initial_capital, 3.0)
size_scalar = base × exposure × governance × meta
notional = effective_cap × size_scalar
→ drawdown taper (linear 1.0→min between start_dd/end_dd)
→ cap by max_position_pct_of_equity
→ cap by risk_per_trade_pct (skip if below min_viable_position_pct)
→ PEK budget enforcement (Phase 1b — closes lowest-ranked if portfolio notional exceeds max_leverage × equity × tolerance)
```

**Kelly multiplier (P2, disabled by default):**
```
size_scalar = base × kelly_multiplier × exposure × governance × meta × drawdown_taper
```
Where `kelly_multiplier = compute_kelly_multiplier(calibrated_prob, tp_mult, sl_mult)`.
Kelly flows through the sizing chain as an extra scalar before position caps.

**PEK budget enforcement (Phase 1b):**
If total portfolio notional exceeds `max_leverage × equity × tolerance`, the lowest-ranked
admitted positions are closed by `_phase_1b_admission_review()`. This replaces the old
per-cycle atomic leverage budget decrement and backstop multiplier pattern.

MT5 positions are sized independently:

```
mt5_equity = broker.get_account_summary().portfolio_value
notional = mt5_equity × max_position_pct_of_equity × drawdown_taper
→ cap by risk_per_trade_pct (skip if below min_viable)
→ validate min volume via _quantity_to_lots()
```

Log lines: `SIZING` (paper) and `MT5_SIZING` (MT5) with all decomposed factors.

## Common Tasks

### Run Paper Trading
```bash
PYTHONPATH=$PYTHONPATH:. python paper_trading/ops/monitor.py
```

### Slack Alerter (optional, requires SLACK_WEBHOOK_URL env var)
```bash
PYTHONPATH=$PYTHONPATH:. python paper_trading/ops/slack_alerter.py
```

### Full Launcher (MT5 + Dashboard + Slack Alerter)
```bash
./monitor_all
```

### Retrain All Assets
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/training/retrain_all_fixed.py
```

### Train Regime Models
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/training/train_regime_models.py
```

### Walk-Forward Backtest (diagnostic)
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/backtest/walk_forward_backtest.py --asset GBPCAD
```

### PnL Backtest from Signal Parquets
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/backtest/backtest_pnl.py
```

### PnL Backtest with Weight Strategy
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/backtest/backtest_pnl.py --weight-method factor_constrained_v1
```

### Compare Ensemble vs Base
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/backtest/backtest_pnl.py --tag base --ensemble-tag ensemble
```

### Train Calibration Models
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/training/train_calibration.py
```

### Reconstruct Historical Portfolio Weights
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/replay/replay_rebalance.py --verify
```

### Daily Monitoring
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/ops/monitor_paper_trading.py
```

### Check Dashboard
```bash
curl http://127.0.0.1:5000/state.json | python3 -m json.tool
```

## Go/No-Go Checklist (Paper Trading → Live)

| Check | Target | Source |
|-------|--------|--------|
| Gate override rate | <40% all assets | monitor csv |
| Mean confidence | >0.52 for ≥14/16 | monitor csv |
| Signal flips | ≤3/day for ≥14/16 | monitor csv |
| Cross-asset correlation | no unexplained >0.7 | monitor csv |
| MT5 errors | zero | engine logs |
| Trades executed | ≥10 across portfolio | MT5 terminal |

6/7 pass → go live at 50% position size for 2 weeks, then full size if live Sharpe tracks within 0.2 of backtest Sharpe.

## Security

The dashboard HTTP server (`paper_trading/serve.py`) supports optional bearer-token authentication.

- **Config**: Set `EIGENCAPITAL_API_TOKEN` env var, or `api_token` in `configs/domains/infrastructure/config.yaml`. Env var takes precedence.
- **Behavior**: If a token is configured, all JSON API endpoints and POST endpoints require `Authorization: Bearer <token>`. Static files (HTML/CSS/JS) are accessible without auth.
- **Default**: No token configured = open access (safe because the server binds to 127.0.0.1 by default).
- **Bind address**: Override with `EIGENCAPITAL_BIND` env var. Warning is logged if binding to anything other than 127.0.0.1.
- **CORS**: Restricted to `http://127.0.0.1:3000` (Vite dev server) and same-origin. No wildcard.

## Structural Limitations (Permanent)

- **BUY signal inversion (6 assets — CADCHF, EURAUD, EURCHF, GBPCHF, GBPJPY, NZDCHF)**:
  The feature space encodes SELL alpha but not BUY alpha for these assets.
  Counterfactual walk-forward ablation disproved both carry and DXY as causal
  mechanisms. SELL_ONLY filter is the correct long-term answer, not a stopgap.
  Recovery requires new feature R&D or separate BUY/SELL classifiers.
  See the 2026-06-20 diagnostic chain in walk-forward backtest and SHAP audit
  for full evidence.

## Direction-Conditional Confidence Thresholds (ADDED 2026-07-11)

Global defaults deployed in `configs/domains/risk/sizing.yaml`:
- `min_confidence_buy: 45.0` — lower BUY threshold unlocks marginal trades (GC +265R, AUDJPY +130R)
- `min_confidence_sell: 55.0` — maintains SELL discipline (72.4% SELL WR)

Signal derivation pipeline (`decision_pipeline.py:apply_confidence_gate`):
1. Determine direction: BUY if `p_long > 0.5`, SELL if `p_long < 0.5`
2. Check buy_threshold: `p_long >= buy_th` for BUY
3. Check sell_threshold: `1 - p_long >= sell_th` for SELL
4. Fallback chain: per-asset direction override → global direction default → per-asset global → global default → 0.55

Per-asset BUY threshold overrides (`min_confidence_buy: 40`):
- **AUDJPY**: +130.2R improvement (134 additional trades at 40% threshold)
- **EURCHF, GBPCHF, GBPJPY**: 40% BUY override (calibrator-inverted assets — these produce 0 BUY signals in practice due to SELL_ONLY filter)
- **GC**: +265.0R improvement (185 additional trades at 40% threshold)

Previous single-threshold overrides (NZDCAD, NZDUSD at 40%) now use the direction-conditional
system, with BUY threshold at 40% and SELL threshold at default 55%.

Backtest vs no-gate baseline: **+313.60 R improvement** from the combined pipeline
(DirectionalCalibrator + direction-conditional thresholds + per-asset overrides).

## Per-Asset Adaptive Exit Gate (ADDED 2026-07-10)

- **Disabled for 5 assets** where the running-peak trail (33% retrace, production activation thresholds) degrades fixed TP/SL performance by ≥25R: USDCHF (−104R), ^DJI (−81R), CADCHF (−57R), USDCAD (−41R), AUDJPY (−27R). These are high-TP-multiple winners (3.0–4.0R) where the trail clips profits before TP is hit. Config: `adaptive_exit.enabled: false` in each asset's YAML.
- **Re-enabled for 17 assets** where the trail was neutral or beneficial (GBPAUD +91R, EURNZD +89R, GBPCHF +33R, NZDUSD +25R, etc.). The net effect on the 22-asset portfolio: total R improved from +521 (Δ=−101 vs fixed) to +830 (Δ=+209 vs fixed) in the Monte Carlo simulation. CAGR improved from 8.33% to 12.77%.
- **Selection heuristic**: assets where `trail_R < fixed_R` by ≥25R get disabled; all others keep the trail. The 6 assets with aggressive `trail_activation_r: 0.5` (NZDUSD, GBPCHF, GBPAUD, EURNZD, EURAUD, AUDUSD) were evaluated individually — only AUDUSD was borderline (−4.67R degradation, kept enabled).
- **Validation**: The per-asset gate produces +830.41R (vs +621.85R fixed, +521.10R universal trail). Bootstrap p5/p95 improves from $565/$612 to $610/$667.

## Drawdown Prevention Features (ADDED 2026-07-10)

*Root cause analysis* of the 2026 Jan-Feb drawdown (worst 2-month period, −164R, 18.2% WR) found it was **concentrated in 5 assets** (GBPAUD −43R, AUDUSD −42R, EURCHF −37R, NZDUSD −24R, GC −22R) where the model made high-confidence wrong-direction bets for 2 months straight. The market experienced a regime shift (commodity currencies up, USD down, CHF safe-haven bid) but the model was never retrained (`retrain_freq: annual` is descriptive only — no scheduler existed).

Three features added to prevent recurrence:

- **Automatic retraining trigger** (`paper_trading/engine.py`): Every 100 cycles (~50min), checks each asset's model file age. If >90 days since last retrain, calls `train(force=True)`. The `retrain_freq` config is now operational instead of descriptive.
- **Regime transition gate** (`decision_pipeline.py:apply_regime_transition_gate`): Detects bull↔bear transitions (close crossing MA50). After a transition, suppresses entries for 30 days — the window where the model's pre-transition directional bias is most wrong. Added to `DEFAULT_STAGES` after `apply_session_gate`.
- **Calibration drift gate** (`decision_pipeline.py:apply_calibration_drift_gate`): Tracks a rolling 30-trade window of (confidence, outcome) per asset. If mean confidence exceeds mean win rate by >20pp, suppresses entries. Catches the "confidently wrong" pattern (e.g., p_long=0.01 with 0% WR). Outcome recording wired into `manage_position` flip path. Added to `DEFAULT_STAGES` after `apply_confidence_gate`.

## Known Issues

- **GBPNZD (REMOVED 2026-06-20)**: tp/sl ratio 0.33 required 75% breakeven WR, model achieved 72.3% — net-negative. Removed from trading.
- **AUDNZD ensemble**: Ensemble degrades signal quality (IC -0.020 in pilot). Confirmed portfolio-wide by walk-forward (p=0.83 pooled); ensemble disabled 2026-06-20 (see ADR-026).
- **Small MT5 equity ($107 demo)**: 0.01 lot minimum for forex (≈$1,150 notional on EURUSD) far exceeds the MT5 position budget (≈$15.67 at 15% of $104). MT5 positions quantize to 0.01 lots regardless of computed size. Leverage budget is deferred for MT5 — revisit when equity > $10K.
- **SL/TP triple bug (FIXED 2026-06-16)**: Three independent issues (deactivated `atr_mult_tp`, uncalibrated `atr_mult_sl`, TP compiler convexity applied to inflated SL distance) produced TP distances up to 44%. Fixes: (1) `_atr_barriers()` now uses `atr_mult_tp` for TP vol basis, (2) `tp_compiler.py` caps R:R at `MAX_RR=5.0`.
- **THIN liquidity (FIXED 2026-06-17)**: THIN regime was routing to hard_reasons (halted all assets). Fixed: only STRESSED halts; THIN → soft_warnings (SL/size adjust, no halt).
- **Prob drift min samples (FIXED 2026-06-17)**: Raised from 3 to 10 for stable mean estimate before confidence drift halt check activates.
- **Entry price deviation gate (ADDED 2026-06-17)**: `entry_service.py` compares `asset.current_price` to signal `entry_price` before submitting. Skips if deviation > `max_entry_slippage_pct` (default 2%).
- **Profit lock gate (ADDED 2026-06-17)**: `decision_pipeline.py` checks unrealized PnL before flipping. Blocks flip if PnL > `profit_lock_threshold_pct` (default 15%).
- **Position sizing guardrails (ADDED 2026-06-17)**: drawdown taper (linear between start_dd/end_dd), per-position equity cap, risk-per-trade cap, portfolio leverage budget (atomic lock decrement), backstop decay (penalty × 0.9/cycle on breach-free cycles).
- **Independent MT5 sizing (ADDED 2026-06-17)**: MT5 computes own qty from broker equity with separate drawdown taper and risk cap. Paper sizing unchanged at $100K equity.
- **Ensemble breakdown logger column prefix (FIXED 2026-06-19)**: `_log_ensemble_breakdown` used `f"{asset_name_u}_carry_vol_adj"` but actual feature columns use `CLOSE_` prefix (from `prices.to_frame("close")`). All feature contributions logged as NaN. Fixed in `paper_trading/inference/pipeline.py:302`.
- **Carry feature always zero (FIXED 2026-06-19)**: `rate_diffs` DataFrame in `data_fetch.py:442` used `asset_name` column key, but `build_alpha_features` looks up by `"close"` — so rate_diff lookup always failed and carry was `pd.Series(0.0)`. Affected all assets, both training and inference (same code path), so no training-inference mismatch — carry was simply inert. Fixed column name to `"close"`.
- **Bar-jump suppression (ADDED 2026-06-19)**: `decision_pipeline.py:apply_bar_jump_suppression` — suppresses all trading for 60 minutes when bar count changes >100 (indicating data-source switch). Stage 0 in DEFAULT_STAGES. Detection in `pipeline.py:_detect_bar_jump()`.
- **Risk-off suppression for AUDUSD (ADDED 2026-06-19)**: `decision_pipeline.py:apply_risk_off_suppression` — holds flat for AUDUSD when VIX is rising (>0) and SPX is falling (<0). AUDCHF was originally included but removed from trading 2026-06-20. Detection in `pipeline.py:_detect_risk_off()` via `features_df["vix_mom_5d"]` and `features_df["spx_mom_5d"]`. Stage after `resolve_signal` in DEFAULT_STAGES.
- **Return computation denominator using rebalanced capital_base (FIXED 2026-06-22)**: `engine_state_service.py:_compute_portfolio_summary` used `sum(a.capital_base)` as the return baseline, but `capital_base` is overwritten by rebalancing to equal `total_value * weight`, making `(mtm_total - tc) / tc ≈ 0%` regardless of actual PnL. A `-16.97%` loss was reported as `+0.04%`. Fix: replaced `sum(a.capital_base)` with `get_config().capital` — the immutable config baseline. Also fixes `realized_return` which used the same `tc`. Also corrected the misleading comment that claimed this was intentional.
- **NQ price deviation gate blocking all entries (FIXED 2026-06-22)**: All 258 "entry skipped" events on NQ were caused by the 2% default `max_entry_slippage_pct` being too tight for volatile Nasdaq-100 futures. Deferred entries saw >2% price moves between signal generation and execution. Fix: added per-asset `max_entry_slippage_pct: 5.0` to NQ config in `configs/domains/assets/NQ.yaml`. The code at `entry_service.py:201` already supports per-asset override with global fallback — no logic change needed.
- **MT5 orphan dry-run Phase C (ADDED 2026-06-22)**: `orchestrator/orphan_reconciliation.py:OrphanReconciler._phase_c_orphan_report()` (extracted from `engine.py` 2026-07-06) — log-only orphan reporter. Logs every MT5 position with no matching paper-side ticket. Deduped by ticket, tracks first_seen cycle, flags removed-asset orphans with `engine_actor=None`. No state mutation. Run for at least one full cycle to produce a clean list before designing adoption/close/manual logic.
- **Position concentration check (ADDED 2026-06-22)**: `orchestrator/correlation.py:compute_position_concentration()` (extracted from `engine.py` 2026-07-06) — counts open long/short positions each cycle, logs WARNING when skew exceeds `net_short_concentration_threshold` (default 75%). Exposed in `state.json` portfolio as `position_concentration` dict. Config key: `defaults.net_short_concentration_threshold` in `configs/domains/risk/sizing.yaml`.
- **Risk-off consequence validated (2026-06-19)**: Checked 63 trading days (3 months) — risk-off (VIX>0 & SPX<0) occurred on 12 days vs the 1 live episode. AUDUSD always-long accuracy: 8.3% on risk-off days vs 54.9% on normal days. Mean-reversion (oversold→BUY) accuracy: 14.3% (1/7) on risk-off+oversold vs 100% on normal+oversold (2/2). Consequence generalizes — the suppression rule is not tuned to one episode.
  **Note on methodology:** This finding is *not* based on counting intraday prediction cycles. It was validated using daily-resolution historical price action (63 daily bars × independent forward returns), so it is exempt from the per-cycle-counting artifact that debunked the three-mechanism taxonomy below. The two conclusions came from different evidentiary standards.
- **Prediction taxonomy (CORRECTED 2026-06-19)**: Earlier taxonomy claimed three distinct failure mechanisms across five assets. That taxonomy was based on *per-cycle* accuracy (each ~30s engine cycle counted as an independent prediction), which amplified a 1-2 day directional miss into "hundreds of wrong predictions." A daily-bar XGBoost model updates once per day; ~500 intraday cycles all reproduce the same daily signal. The live window was **3 calendar days (Jun 17-19)**. Honest per-day accuracy:

  | Asset | Daily acc | Days | Actual best description |
  |-------|-----------|------|------------------------|
  | AUDUSD | 0/2 (0%) | 2 | **CONFIRMED** — risk-off degrades mean-reversion (validated across 12 independent risk-off episodes over 3 months of historical data). Risk-off suppression addresses this. |
  | AUDCHF | 2/2 (100%) | 2 | Fine at daily level. Earlier "risk-off failure" was micro-PnL noise, not directional failure. |
  | NZDUSD | 0/2 (0%) | 2 | **Watch**: same direction as AUDUSD's risk-off failure (both wrong on BUY) but unconfirmed. Re-check once more days accumulate. |
  | EURUSD | 1/3 (33%) | 3 | Flipped to SELL on Jun 18 and was correct, but 2/3 wrong overall. Too little data to distinguish real flip-detection from chance. |
  | GBPNZD | 1/2 (50%) | 2 | Coin flip over 2 days. Earlier "opposite pattern" was overinterpretation. |
  | AUDNZD | 2/2 (100%) | 2 | Correct — control asset works. |
  | CADCHF | 1/3 (33%) | 3 | Low accuracy but predicts both directions. Underdetermined. |
  | EURAUD | 1/3 (33%) | 3 | Low accuracy, both directions. Underdetermined. |

  **Only AUDUSD risk-off suppression is a validated claim.** All other "globally wrong" / "confidence-independent" / "risk-off dependent" labels were per-cycle counting artifacts. NZDUSD (0/2, never flipped) is the only remaining genuine concern, but 2 days does not support a mechanism claim.

  **Label barrier-asymmetry hypothesis (2026-06-19) — FALSIFIED**: Testing showed no correlation between TP/SL ratio and prediction accuracy. AUDNZD has the most BUY-biased labels (3.7x ratio of BUY:SELL labels) yet predicts 95% correctly. NZDUSD has nearly balanced labels (1.2x ratio) yet predicts 0% correctly. AUDUSD has SELL-biased labels (0.36x) yet the model predicts BUY — going against the label distribution. The model learns the actual training-period trend, not the barrier geometry.

- **Retrain with carry (2026-06-19)**: All 22 assets retrained after carry bug fix (carry was always zero). Carry is now 8-16% of feature importance across key FX assets. Post-retrain historical replay against 13 risk-off episodes shows:
  - **AUDUSD**: Risk-off accuracy improved from 8.3%→38.5% but still lags normal (54.0%). Suppression still justified.
  - **AUDCHF**: Risk-off accuracy 38.5% vs normal 58.0%. Model more confidently BUY on risk-off (P=0.709 vs 0.652). Suppression still needed.
  - **GBPNZD**: Normal-day accuracy jumped from ~1%→62%. The "opposite pattern" was a carry-deprivation artifact — no longer deferred.
  - **NZDUSD/EURUSD**: No clean historical shortcut — paper-only observation required. Minimum 10 trading days before any directional conclusion.

  **Note on AUDCHF carry entanglement**: Carry being #3 feature (10.7%) made AUDCHF's risk-off failure *more* pronounced (P=0.709 on risk-off vs 0.652 normal), not less. Possible mechanism: carry trade unwinds are a classic feature of real risk-off episodes; a model now using carry more heavily may be doubling down on a carry-trade-direction read that reverses during risk-off. Worth investigating if revisiting the risk-off mechanism.

- **Signal chatter + MT5 orphaned positions (FIXED 2026-06-17)**: fixes applied:
  - (1) `decision_pipeline.py:apply_signal_stability_filter` — margin widened 0.05→0.15, now checks max(prob_long, prob_short). Requires >0.65 conviction on either side to proceed.
  - (2) `decision_pipeline.py:apply_signal_hysteresis` (NEW) — 2-of-3 signal agreement required before a flip is allowed.
  - (3) `decision_pipeline.py:manage_position` — `_can_enter()` checked BEFORE `_close_position()`. If cool-down blocks re-entry, old position is kept open.
  - (4) `engine_state_service.py` — `mt5_ticket` now persisted in snapshot.
   - (5) `position_service.py` — MT5 close failures logged as ERROR with "position may be orphaned".

- **pipeline.py indentation nesting (FIXED 2026-06-19)**: `_detect_bar_jump()` was accidentally defined at module level (0 indent) between `_ensure_ready()` and all remaining class methods. Everything from `_fetch_and_prepare_data` onward (16 methods, lines 119-577) was nested inside `_detect_bar_jump` as local inner functions instead of being class methods. This meant none of those methods were callable from `_generate_and_apply`. Fix: indented `_detect_bar_jump` by 4 spaces (class method) and changed the call site from `_detect_bar_jump(asset, ...)` to `self._detect_bar_jump(asset, ...)`.

- **Spread gate (ADDED 2026-06-19)**: `decision_pipeline.py:apply_spread_gate` — blocks entries when spread exceeds per-asset-class threshold. Uses live MT5 bid/ask spread (bps) from `mt5_client.realtime_spread()`. Fail-closed: if spread data is missing or stale (>300s), entry is blocked. Per-asset-class tiers: `fx_major` (10bps), `fx_cross` (20bps), `indices` (15bps), `metals` (20bps). Observe-only mode for first 720 cycles (~6h at 30s cadence) logs what it *would* block without actually blocking — sized to span varied intraday conditions (opens, mid-session, closes). Detection in `pipeline.py:_generate_and_apply -> asset.refresh_spread()`.

- **Regime model at inference (FIXED 2026-06-19, commits f15af30, b980f69)**: Two independent bugs kept the regime model from contributing to ensemble blends:
  1. **Load guard**: `training.py:_train_regime_if_configured` checked `if not regime_feats: return` before attempting to load from disk. `regime_feature_names` was initialized to `[]` in `__init__`, so the guard always fired — load was never attempted. Fix: attempt disk load before the guard; on success, populate `regime_feature_names` from the loaded model's `_feature_names`.
  2. **Missing features at inference**: `pipeline.py:_build_feature_set` built `features_df` from alpha (13 cols) + archetype (4 cols) only. The regime model was trained with 20 columns (13 alpha + 7 regime-specific like `GC_hurst`). The 7 regime columns were absent at inference, so `regime_available` was always empty and the blend silently skipped. Fix: generate regime features from OHLCV, prefix per-asset, join into `features_df`.
  **Result**: After both fixes, 22/22 trace decisions show varying `regime_long_prob` (range 0.0575–0.8659, 22 unique per-cycle). Cross-asset and across-time variance confirmed. The "12 trades all neutral" hypothesis from the Pre-fix era was not a neutral market — it was a dead regime model silently contributing constant noise.
  **Hurst constant (FIXED b980f69)**: `compute_hurst` used `rolling().apply(hurst_calc)` with `raw=False` (default), passing a pandas Series with DatetimeIndex. Inside `hurst_calc`, `z[lag:]` used label-based datetime indexing — integer lags didn't match dates, always returning the fallback 0.5. Fix: `raw=True` passes numpy arrays → positional indexing works. Post-fix: AUDUSD hurst varies from 0.19–0.40 (vs flat 0.5 everywhere pre-fix).
  **Cycle-1 cold-start transient**: The first inference cycle post-restart uses 200 rows (truncation validation hasn't run yet → `_truncate_inference=False`). Cycles 2+ use 1 row. The regime output differs between the two (NZDCAD 0.7397→0.2130). Cycles 2→3→4 are bit-for-bit identical for all 22 assets (Δ=0.0000). Mitigation: `apply_first_cycle_suppression` stage added to `DEFAULT_STAGES` — suppresses all trading on cycle 1 after a cold start.
  **Pre/post-fix boundary**: Any trades executed prior to commit `f15af30` (2026-06-19) used a regime-dead ensemble. Do not pool pre-fix and post-fix trades into a single exit-reason or performance aggregate — they reflect different systems.

- **Position concentration alert (IMPLEMENTED 2026-06-23)**: `orchestrator/correlation.py:compute_position_concentration()` emits a `position_concentration` WAL event every cycle with skew, threshold, dominant_side, and alert boolean. The slack alerter at `slack_alerter.py:166` handles it with state-transition cooldown: fires immediately on onset, sends an "all clear" when skew drops below threshold, and sends a heartbeat every hour while sustained. The emit-every-cycle design (not just on alert conditions) enables the alerter to detect both below→above and above→below transitions by diffing the continuous signal.
- **WAL `os.fsync` exception gap (FIXED 2026-06-25)**: Code review confirmed all three orchestrator-level WAL write calls (`position_concentration` line 405, `actor_health` line 585, `state_committed` line 605) already wrapped in try/except; `WalWriter.flush()` already catches `OSError` on `os.fsync`. The gap described in the original identification was closed by a prior session — no action needed.
- **Emergency halt loop (FIXED 2026-07-03)**: Stale `data/live/state.json` with `emergency_halt=True`, `peak_portfolio_value=75000.0`, and live equity ~74960 caused an infinite early-return loop during BTC weekend trading. Root cause chain:

  1. **Bug-Alpha: `_cycles_elapsed` never incremented** — `_cycles_elapsed += 1` was inside `_pre_phase_pek()`, which never runs when `_emergency_halt=True`. Moved to top of `_run_phases` so counter increments every cycle regardless of halt state.
  2. **Stale peak from prior session** — The persisted peak from a May session with different capital base was lower than live equity, creating a false +drawdown at restart. Fixed: re-anchor `_peak_portfolio_value >= live equity` at init.
  3. **No auto-clear on restart** — Snapshot restores `_emergency_halt=True` from stale state.json but never verified whether the halt is still warranted. Fixed: init-time auto-clear clears halt when equity >= 99% of peak and reason is DRAWDOWN or CONSECUTIVE_LOSSES.
  4. **Critical files**: `paper_trading/orchestrator/engine.py` (auto-clear, peak re-anchor, cycle counter position), `tools/reset_halt.py` (operator CLI), `paper_trading/services/engine_state_service.py` (persist-boundary observability), `paper_trading/alerting/manager.py` (Slack alert on auto-clear).

  **Validation**: 12 new regression tests cover weekend cycle scoping, halt early-return, counter increment under halt, and per-cycle auto-unhalt eligibility. 2746 tests pass (7 pre-existing unrelated failures).
- **NZDCAD/NZDUSD confidence gate (PROPOSED 2026-06-23, not implemented)**: As of 2026-06-22 live observation, NZDCAD and NZDUSD show 92-96% confidence every cycle, with no win-rate data to assess whether this reflects genuine skill or miscalibration. The calibration question (does confidence track actual win rate?) is gated on N≥20 trades — fewer than 20 trades is insufficient to distinguish. Proposal: add a check to `scripts/ops/monitor_paper_trading.py` that prints "READY FOR REVIEW" once either asset reaches `n_trades >= 20`. What "READY FOR REVIEW" should trigger: compare the asset's mean confidence (from `mean_confidence` in state.json) against its actual win rate across those trades. If win rate tracks confidence within ±10pp, the model is calibrated and the high confidence is explanatory. If win rate lags confidence by >15pp (e.g., 92% confidence with 60% win rate), the model is overconfident on these pairs — same pattern as the BUY inversion discovery. The `n_trades >= 20` floor is the gate; the comparison script does not exist yet.
---

## Historical Research Record

The full historical research record (Walk-Forward PnL Backtest, BUY Inversion Discovery, SHAP Audit, Replay-First Architecture, Barrier Symmetry Audit, Statistical Metrics, Trend-Exhaustion Features, TP/SL Optimizer, Codebase Remediation, Portfolio Remediation, Adaptive Exit Engine, Shock Simulation, Production Audit Remediation, Dashboard Redesign, Project Rename, Weekend Trading) has been moved to `docs/RESEARCH_HISTORY.md`.

Key conclusions that remain relevant to current operations:

- **Ensemble disabled** — base_weight=1.0 portfolio-wide (see ADR-026). Regime features still computed at inference for trace logging.
- **SELL_ONLY** — 6 permanent assets (CADCHF, EURAUD, EURCHF, GBPCHF, GBPJPY, NZDCHF). See config-driven `get_sell_only_assets()` in `paper_trading/execution/gate_constants.py`.
- **Adaptive exit engine** — 4-stage retracement trailing (breakeven lock → R-based scale-out → retracement trail → time decay). Config per asset.
- **Factor constraints** — `factor_constrained_v2` with hard linear inequality constraints, pinning CHF at 20%.
- **Drift detector** — live win-rate drift against breakeven WR; dashboard at `/optimization.json`.
- **Doc-drift CI check** — `tools/doc_drift_check.py` runs 12 cross-reference checks in CI.

