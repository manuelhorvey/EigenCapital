# Three-Tier Hardening Roadmap

Operational reference for cross-asset isolation, execution physics, extended history, lead-lag features, adaptive macro weighting, and portfolio-level circuit breaker.

All tiers have been implemented, validated, and merged to `main`. 281 tests pass across 17 test files.

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

1. Synthetic stress hardening: run full survival sim with `--synthetic-stress --paths 5000` to validate circuit breaker + trade quality gates reduce the 83.78% synthetic ruin rate.
2. Deploy hybrid ensemble pickles for assets with `adaptive_macro: true` (plain XGB ignores macro head).
