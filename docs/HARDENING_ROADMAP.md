# Three-Tier Hardening Roadmap

Operational reference for cross-asset isolation, execution physics, extended history, lead-lag features, and adaptive macro weighting. Implemented on branch `feat/three-tier-hardening`.

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

## Tier 3 — Extended history, lead-lag, adaptive macro

### 3A — Extended history

| Step | Command / artifact |
|------|-------------------|
| Download 2000+ OHLCV | `python data/loaders/backfill_to_2000.py` |
| Neutral prediction stubs | `python scripts/run_extended_history_pipeline.py` |
| Extended survival sim | `python research/risk/survival_sim.py --extended-history --regime-bootstrap ...` |
| Export metrics | `data/research/survival_extended.json` (auto when `--extended-history`) |
| Compare 5y vs 25y | `python diagnostics/extended_history_report.py` |

- `features/builder.py` — `compute_training_data_extended()` for full-history feature matrices.
- `research/risk/synthetic_stress.py` — `adjust_injection_rate_for_crisis_density()` lowers synthetic injection when empirical CRISIS density is already high.

**Tests:** `tests/test_synthetic_stress_extended.py`

### 3B — Lead-lag

| Step | Command / artifact |
|------|-------------------|
| Full matrix + heatmap | `python research/lead_lag/run_lead_lag.py` |
| Matrix parquet | `data/research/lead_lag_matrix.parquet` |
| Heatmap PNG | `data/research/lead_lag_matrix.png` |
| Curated edges | `data/research/lead_lag_edges.yaml` |

- `features/lead_lag_features.py` — loads edges; `features/builder.py` attaches columns listed in `custom_features`.
- Example: **AUDJPY** uses `nzdjpy_lead_3` (NZDJPY leads by 3 days) — registered in `features/registry.py`.

**Tests:** `tests/test_lead_lag_heatmap.py`

### 3C — Adaptive macro weight

- `models/macro_expert_head.py` — `online_weight=True` tracks rolling Sharpe; soft-updates blend weight in **[0.25, 0.65]**.
- `configs/paper_trading.yaml` — `adaptive_macro: true` on **NZDJPY** (requires a model pickle with `macro_head`, e.g. `HybridRegimeEnsemble`).
- `paper_trading/asset_engine.py` — directional macro vs blend feedback on trade close; `macro_weight` exposed on decision JSON.

**ADR:** [ADR-022](adr/ADR-022-macro-adaptive-weight.md)  
**Tests:** `tests/test_macro_adaptivity.py`, `tests/test_macro_trade_feedback.py`

---

## Quick validation

```bash
pytest tests/test_feature_isolation.py tests/test_sizing.py \
  tests/test_paper_broker.py tests/test_execution_bridge.py \
  tests/test_lead_lag_heatmap.py tests/test_macro_adaptivity.py \
  tests/test_synthetic_stress_extended.py -q
```

---

## Remaining operational work

1. Run extended-history backfill and survival comparison on real data.
2. Refresh `lead_lag_edges.yaml` after `run_lead_lag.py` and retrain affected assets if edges change.
3. Deploy hybrid ensemble pickles for assets with `adaptive_macro: true` (plain XGB ignores macro head).
