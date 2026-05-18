# ADR-011: Known Issues Scheduled for January 2027 Retrain

## Status

Accepted — documented during May 2026 codebase review. Fixes deferred to avoid
disrupting the active paper trade evaluation period (May–November 2026).

## Context

A comprehensive codebase review (2026-05-17) identified two architectural issues
that cannot be fixed during the paper trade freeze without invalidating the
performance measurement baseline.

### Issue C3: Dual PnL Accounting in AssetEngine (RESOLVED)

**File:** `paper_trading/engine.py` — `update_pnl()` method (lines 340–387)

The engine tracks PnL through two overlapping mechanisms:

1. **Position-based PnL** — `_open_position()` / `_close_position()` manages
   SL/TP exits and records trade-level returns in `self.trade_log`.
2. **Signal-based daily PnL** — `update_pnl()` also computes daily returns from
   the previous bar's signal direction (lines 373–387) and adds them to
   `self.current_value`.

When a position is open and the daily signal agrees with the position direction,
both mechanisms contribute PnL to `self.current_value`, creating double-counting.
The SL/TP path returns early (line 370), so the overlap only occurs on bars where
no SL/TP is hit.

**Impact:** Portfolio value tracking may overstate or understate actual performance
during open positions. The magnitude depends on position duration and signal
stability. This does not affect model training or signal generation — only the
paper trading PnL ledger.

**Resolution:** Added an early return in `update_pnl()` after the SL/TP check
when a position is still open (`paper_trading/engine.py:372`). This prevents the
signal-based daily PnL path from executing during open positions, ensuring a
single PnL path:
- Position open → position-based PnL only (booked on close via `_close_position`).
- No position open → signal-based daily PnL.
- Unit tests added in `tests/test_engine.py::TestUpdatePnl`.

### Issue A1: Research vs Paper Trading Model Architecture Split

**Research pipeline** uses `HybridRegimeEnsemble`:
- Global XGBoost backbone (max_depth=2, 100 trees)
- Regime-specific expert heads (per TREND/RANGE/VOLATILE)
- Protected macro expert head (0.45 blend weight)
- Full feature manifold: base + regime + structural + interaction + macro
- Directional prior adjustments + transition penalty

**Paper trading pipeline** uses standalone XGBoost per asset:
- Single XGBoost (max_depth=2, 300 trees)
- 4 macro features only (e.g., rate_diff, yield_delta, momentum, relative strength)
- No regime routing, no expert heads, no interaction features
- Fixed confidence threshold (0.45)

These are fundamentally different architectures. The paper trade validates the
simple 4-feature model, which is the one that cleared the walk-forward bootstrap
gates. The ensemble architecture has not been validated through the same
walk-forward rigor for the production asset set (XLF, BTC, NZDJPY, USDCAD).

**This is acceptable for now** — the 4-feature model is the one with proven
walk-forward stability. But the January retrain must decide:

1. **Keep simple:** Continue with 4-feature macro models per asset. Advantages:
   fewer parameters, less overfitting risk, interpretable.
2. **Graduate ensemble:** Port the `HybridRegimeEnsemble` to paper trading with
   full walk-forward validation. Advantages: richer signal, regime awareness.
3. **Hybrid:** Use ensemble for research/signal generation but keep simple models
   as a fallback/comparison.

## Decision

Both issues are documented and deferred to the January 2027 retrain cycle.
No changes to model training, signal generation, or PnL accounting will be made
during the paper trade freeze (May–November 2026).

## Consequences

- Paper trading PnL metrics (total return, drawdown, profit factor) may have
  small inaccuracies due to C3. These do not affect trading decisions.
- The paper trade evaluates the simple 4-feature architecture, not the ensemble.
  November evaluation criteria should be interpreted in that context.
- January 2027 retrain priorities:
  - ~~Fix C3 dual PnL accounting~~ **Done**
  - Retrain with vol-adjusted barriers (ratio diagnostic from weekly report)
  - ~~Add unit tests for HybridRegimeEnsemble and RegimeClassifier~~ **Done**
  - Decide canonical model architecture: simple 4-feature vs ensemble
  - ~~Remove unused dependencies (lightgbm, catboost, mlflow, optuna)~~ **Done**
  - ~~Fix coverage source config in pyproject.toml~~ **Done**
