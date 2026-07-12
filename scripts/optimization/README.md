# TP/SL Optimizer Package

Tools for grid-search, validation, and live monitoring of per-asset TP/SL configurations.

## Scripts (execution order for a full optimization cycle)

1. **`trade_outcome_repository.py`** — Export trade data from SQLite as a flat DataFrame, enriched with per-asset config params (tp_mult, sl_mult, allocation, sell_only flag). Required first step for all downstream scripts.

2. **`directional_win_rate.py`** — Per-direction BUY/SELL win rate breakdown. Flags assets where one direction significantly underperforms the other.

3. **`per_asset_quality.py`** — Quality classification per asset: expected value (EV), breakeven win rate, MAE/MFE ratios. Identifies assets where tp/sl ratio is misaligned with model skill.

4. **`portfolio_sltp_optimizer.py`** — Core optimizer. Two-pass log-space grid search over ratio space [0.1, 20.0] with geometric mean constraint preserving average barrier distance. Outputs optimal ratio per asset and portfolio-level ΔR estimates.

5. **`risk_compression.py`** — Stress scenario injection. Tests TP/SL configurations against synthetic risk-off shocks to verify robustness under adverse conditions.

6. **`sl_fragility_test.py`** — SL hit rate validation using 4h OHLCV data. Compares intraday wick-hit probability vs daily-close hit probability. Flags assets where the new SL would be triggered too frequently intraday.

7. **`portfolio_balancer.py`** — Correlation-aware cluster risk penalty. Applies discount multipliers to high-correlation asset clusters (Equity 15%, CHF 5%, NZD 5%). Produces balanced portfolio-level ΔR estimates.

8. **`drift_detector.py`** — Live monitoring script. Compares per-asset win rate against breakeven WR. Outputs JSON for the dashboard `/optimization.json` endpoint. Designed for cron-based periodic execution.

## Usage

```bash
# Step 1: Export outcomes from SQLite
PYTHONPATH=$PYTHONPATH:. python scripts/optimization/trade_outcome_repository.py

# Step 2: Full optimizer pass
PYTHONPATH=$PYTHONPATH:. python scripts/optimization/portfolio_sltp_optimizer.py

# Step 3: Validate SL fragility
PYTHONPATH=$PYTHONPATH:. python scripts/optimization/sl_fragility_test.py

# Step 4: Live monitoring (cron: */30 * * * *)
PYTHONPATH=$PYTHONPATH:. python scripts/optimization/drift_detector.py --json > data/live/optimization.json
```

## 2026-06-30 Results

- 11 assets bumped to ratio=3.0 (from <3.0)
- 10 assets left unchanged (already >=3.0)
- SL fragility: 20/21 OK, 0 CRITICAL, 1 FRAGILE (NZDCAD, 0.22% hit rate)
- All 21 models retrained with new labels
- Walk-forward: total_R=367.84 (+16.2%), max_dd_R=-0.9 (-54.7%)
