# EigenCapital — Architecture Reference

System architecture, component descriptions, and design decisions for developers.

**Last updated:** 2026-07-19

---

## Project Identity

Cross-sectional multi-asset paper trading engine. 22-asset portfolio (FX, commodities, indices + BTCUSD) with per-asset XGBoost models, 17-layer governance (core) + 3 adaptive budget layers + decision pipeline + position sizing guardrails, adaptive exit engine, and MT5 bridge execution (Exness demo via Wine).

---

## Architecture Overview

### Models

- **Primary**: Per-asset XGBClassifier (base only)
- **Regime**: Regime-conditional ensemble **disabled** 2026-06-20 (walk-forward p=0.83; see ADR-026)
- **Training**: Expanding-window, `scale_pos_weight`, meta-labeling
- **Data source**: Expanded cache (`data/yfinance_10yr/`) providing 10y+ history per asset

### Features

40 alpha columns per asset:
- 9 core + 6 trend-exhaustion
- 2+ COT z/change
- 4 cross-asset + 10 directional momentum/carry splits
- 15 FXStreet narrative cross-asset features
- Up to 16 additional COT pair columns
- 6 regime features (hurst, kaufman_er, adx, vol_zscore, compression, session_vol_profile)

See `docs/FEATURES.md` for canonical taxonomy.

### Labels

- Triple-barrier with per-asset pt_sl
- `vertical_barrier=20`, gap >= vb
- Purged walk-forward folds

### Configuration

- `configs/paper_config_registry.py` + `configs/domains/` — domain-first config tree
- Mode overrides, global defaults, per-asset config
- Environments: `configs/environments/` (live, paper, backtest, research, test)

---

## Portfolio Maturity Framework (P0–P4)

| Layer | Module | Status |
|-------|--------|--------|
| P0 — Weights | `shared/portfolio_weights.py` | Active (8 strategies) |
| P1 — Calibration | `shared/calibration/` | Active (4 calibrators) |
| P2 — Kelly sizing | `shared/kelly.py` | Active, disabled by default |
| P3 — Factor model | `shared/factor_model.py` | Active (10 factor groups) |
| P4 — HRP | `portfolio/hrp_allocator.py` | Active |

All layers are config-gated.

---

## PEK (Portfolio Execution Kernel)

Centralized admission control and risk budgeting, replacing legacy distributed checks.

### Components

| Component | Module | Purpose |
|-----------|--------|---------|
| PortfolioStateSnapshot | `paper_trading/pek/contracts/portfolio_state.py` | Immutable portfolio exposure truth |
| PerformanceState | `paper_trading/pek/contracts/performance_state.py` | System behavioral telemetry |
| RiskBudget | `paper_trading/pek/contracts/risk_budget.py` | Adaptive risk limits |
| PortfolioStateBuilder | `paper_trading/pek/state/portfolio_state_builder.py` | Snapshot factory |
| PerformanceStateBuilder | `paper_trading/pek/perf/performance_state_builder.py` | Outcome tracker + velocity |
| RiskEngineV2 | `paper_trading/pek/engine_v2.py` | Adaptive budget from snapshot + perf |
| PortfolioAdmissionController | `paper_trading/orchestrator/admission/controller.py` | Two-stage filter → rank → enforce |
| AdmissionSignal | `paper_trading/orchestrator/admission/signal.py` | Immutable signal contract |

---

## Inference Pipeline

```
paper_trading/inference/pipeline.py
  → FeatureBuilder (alpha + regime + archetype)
  → Base model predict_proba()
  → Calibration (P1 — DirectionalCalibrator)
  → Governance gates
  → Decision pipeline (25 stages)
  → Execute (via entry_service.py)
```

---

## Orchestrator: 6-Phase Cycle (PRE + 5 Numbered Phases)

The `EngineOrchestrator` (`paper_trading/orchestrator/engine.py`) runs a fault-isolated, phased execution loop using actor-based isolation (ThreadPoolExecutor, 8 workers):

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
    │ VaR / CVaR                   │
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
    ┌───────────────▼───────────────────┐
    │ Position Concentration            │
    │ Net-short skew check              │
    └───────────────┬───────────────────┘
                    │
    ┌───────────────▼───────────────────┐
    │ Phase 4: PERSIST                  │
    │ Flush buffers → SQLite WAL        │
    │ Record outcomes → PerfState       │
    │ State snapshot → state.json       │
    └───────────────┬───────────────────┘
                    │
    ┌───────────────▼───────────────────┐
    │ (next cycle)                      │
    └───────────────────────────────────┘
```

---

## Governance: 25-Stage Decision Pipeline

17 core layers + 3 adaptive budget layers (RiskEngineV2, PEK admission, PerformanceState velocity) + HealthMonitor + VaR/CVaR + RecoveryScheduler + 25-stage decision pipeline + position sizing guardrails.

### Drawdown Prevention Features (ADDED 2026-07-10)

- **Automatic retraining trigger** (`paper_trading/engine.py`): Every 100 cycles (~50min), checks model file age. If >90 days, retrains.
- **Regime transition gate** (`decision_pipeline.py`): Detects bull↔bear transitions (close crossing MA50). Suppresses entries for 30 days after transition.
- **Calibration drift gate** (`decision_pipeline.py`): Rolling 30-trade window. If mean confidence exceeds mean win rate by >20pp, suppresses entries.

---

## Entry Gates

All gates are in `decision_pipeline.py` or `entry_service.py`:

| Gate | Purpose |
|------|---------|
| Price deviation | Blocks if price moved >2% between signal gen and execution |
| Profit lock | Blocks flips when PnL > profit_lock_threshold_pct |
| PEK budget | Closes lowest-ranked if portfolio notional exceeds max |
| Bar-jump suppression | 60-min halt on data-source switch |
| Risk-off suppression | AUDUSD flat when VIX rising + SPX falling |
| Spread gate | Blocks when spread exceeds per-asset-class threshold |
| First-cycle suppression | Blocks all trading on cycle 1 after cold start |
| Signal stability | Requires >0.65 conviction on either side |
| Signal hysteresis | 2-of-3 signal agreement required for flip |
| Direction-conditional thresholds | Separate buy/sell confidence thresholds |

---

## Key Files

| File | Purpose |
|------|---------|
| `configs/paper_config_registry.py` + `configs/domains/` | Domain-first config tree |
| `shared/portfolio_weights.py` | P0 portfolio truth layer (8 strategies) |
| `shared/calibration/` | P1 calibration layer |
| `shared/kelly.py` | P2 fractional Kelly sizing |
| `paper_trading/pek/contracts/portfolio_state.py` | Immutable portfolio exposure |
| `paper_trading/pek/contracts/performance_state.py` | Performance state with regime velocity |
| `paper_trading/pek/engine_v2.py` | Adaptive risk budgeting |
| `paper_trading/orchestrator/admission/controller.py` | PEK admission controller |
| `paper_trading/orchestrator/engine.py` | EngineOrchestrator (5-phase loop) |
| `paper_trading/orchestrator/health.py` | VaR/CVaR, health monitor, circuit breaker |
| `paper_trading/orchestrator/correlation.py` | Position concentration, correlation |
| `paper_trading/orchestrator/orphan_reconciliation.py` | MT5 orphan lifecycle |
| `paper_trading/engine.py` | PaperTradingEngine (main loop) |
| `paper_trading/asset_engine.py` | Per-asset lifecycle |
| `paper_trading/inference/pipeline.py` | AssetInferencePipeline |
| `paper_trading/inference/training.py` | AssetTrainingPipeline |
| `paper_trading/execution/decision_pipeline.py` | Decision pipeline stages |
| `paper_trading/execution/mt5_broker.py` | MT5 execution broker |
| `paper_trading/ops/mt5_client.py` | TCP frame protocol to Wine-hosted MT5 |
| `eigencapital/platform/detector.py` | OS/Wine/deployment mode detection (sys.platform abstraction) |
| `eigencapital/platform/paths.py` | Platform-independent path resolution (replaces hardcoded paths) |
| `eigencapital/platform/process.py` | Cross-platform process discovery, kill, health check |
| `eigencapital/platform/signals.py` | Cross-platform graceful shutdown (threading.Event-based) |
| `eigencapital/platform/mt5_strategies.py` | Strategy pattern: WineMT5Strategy / NativeWindowsMT5Strategy / NoopMT5Strategy |
| `eigencapital/platform/mt5_bridge_manager.py` | MT5 terminal+bridge lifecycle, watchdog, auto-restart |
| `paper_trading/ops/monitor.py` | Main entry point |
| `paper_trading/services/entry_service.py` | Entry validation + sizing chain |
| `paper_trading/services/engine_state_service.py` | Portfolio summary |
| `paper_trading/governance/risk_registry.py` | Per-instance risk state |
| `shared/factor_model.py` | P3 factor model (10 groups) |
| `portfolio/hrp_allocator.py` | P4 HRP allocation |
| `features/alpha_features.py` | Alpha feature builder |
| `features/regime_features.py` | Regime feature builder |
| `features/data_fetch.py` | Data fetching (MT5 / yfinance) |
| `labels/compat.py` | Triple-barrier labeling |
| `shared/vault_secrets.py` | VaultSecretsProvider (optional) |

---

## MT5 Bridge

`paper_trading/ops/mt5_client.py` — TCP frame protocol to Wine-hosted MT5 (port 9879).

- Connection pool with 4 parallel sockets
- Circuit breaker with exponential backoff (30s → 60s → 120s → 300s)
- Heartbeat every 15s
- Idempotency keys to prevent duplicate orders
- Read-back verification for SL/TP modifications

---

## Dashboard

React SPA on port 5000 (`paper_trading/serve.py`), state via `state.json`.

- Bearer-token authentication (optional, mandatory on non-loopback)
- Prometheus metrics (requests, latency, errors)
- CORS restricted to `http://127.0.0.1:3000`
- Full Grafana dashboard available in `ops/grafana/dashboards/`

---

## Structural Limitations (Permanent)

### BUY Signal Inversion (6 assets)

CADCHF, EURAUD, EURCHF, GBPCHF, GBPJPY, NZDCHF — the feature space encodes SELL alpha but not BUY alpha for these assets. Counterfactual walk-forward ablation disproved both carry and DXY as causal mechanisms. SELL_ONLY filter is the correct long-term answer.

### Ensemble Disabled

Regime-conditional ensemble disabled portfolio-wide (walk-forward p=0.83). Regime features still computed for trace logging. See ADR-026.

---

## Key Design Decisions (ADR)

Architectural Decision Records tracked in `docs/adr/ADR-000-index.md` (27 records). Key decisions:

| ADR | Decision |
|-----|----------|
| ADR-001 | Triple-barrier labeling |
| ADR-002 | Regime classifier as router |
| ADR-003 | Expanding train window |
| ADR-006 | XLF primary asset (rejected) |
| ADR-015 | Asset-specific label horizons |
| ADR-020 | Meta-labeling |
| ADR-026 | Ensemble disabled |
| ADR-027 | Portfolio Execution Kernel |
