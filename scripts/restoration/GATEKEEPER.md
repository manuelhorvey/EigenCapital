# SELL_ONLY Filter — Change Gatekeeper

## Purpose

The SELL_ONLY filter blocks BUY signals for 5 assets (CADCHF, ES, NQ, NZDCHF, EURAUD). ^DJI, USDCHF, and EURCHF were removed from SELL_ONLY on 2026-06-26 after trend-exhaustion features improved BuyWR above breakeven. This gate defines the evidence required to modify or remove it.

## Current Status (2026-06-30 — 5 remaining SELL_ONLY assets)

**Structural asymmetry confirmed** — BUY direction is not recoverable for these assets through any tested transformation:

| Experiment | Result | Evidence |
|------------|--------|----------|
| Threshold optimization (0.01-0.99 scan) | Rejected | No threshold produces BUY WR > 50% for any SELL_ONLY asset |
| Rolling 252 window | Rejected | Makes BUY WR worse (p_long mean shifts 0.4→0.6, wrong direction) |
| Label inversion (y'=1-y training) | Rejected | EURAUD BUY WR only improves 22.7%→31.0%, still <50% |
| SHAP-based feature ablation | Rejected (prior) | Carry and DXY removed, neither restored BUY WR > 50% |
| Corrected interpretation (swap signal) | Circular | Same as SELL_ONLY — model predicts one direction, we trade the other |

## Gate Criteria

To modify or remove the SELL_ONLY filter for any asset:

### Phase 1 — Must pass (all required)

1. **Label inversion test** — BUY WR > 50% when training with y'=1-y and evaluating against original labels
2. **Symmetry test** — asymmetry (sell_wr - buy_wr) < 0.15 at default 0.575/0.425 threshold
3. **Information sufficiency** — at least 2 non-SELL_ONLY assets with similar fundamentals (same cluster: CHF-pair or equity-index) must show BUY WR > 50%

### Phase 2 — Must pass (all required)

4. **Shadow mode (30 trading days)** — hypothetical trades (no execution) show:
   - BUY WR > 50%
   - Total R > 0
   - At least 10 BUY trades executed
5. **Walk-forward reproducibility** — 3-fold expanding walk-forward using the new signal source produces BUY WR > 50% on ALL folds

### Phase 3 — Rollback triggers (monitoring)

6. **Three-level tripwire** must remain active:
   - L1: Warning if rolling 20-trade BUY WR < 35%
   - L2: Protection if rolling 40-trade BUY WR < 35% (reduce allocation 50%)
   - L3: Reversion if rolling 60-trade BUY WR < 35% OR rolling BUY R < 0

## Running the Gate

```bash
# Invoke diagnostic suite
PYTHONPATH=$PYTHONPATH:. python scripts/restoration/02_buy_signal_existence_diagnostic.py --asset <ASSET>

# Run with regeneration of inverted labels
PYTHONPATH=$PYTHONPATH:. python scripts/restoration/02_buy_signal_existence_diagnostic.py --asset <ASSET> --rerun-inversion
```

## Falsified Hypotheses (do not revisit without new evidence)

| Hypothesis | Falsified by | Date |
|------------|-------------|------|
| Threshold/cutoff tuning can fix BUY | Threshold scan 0.01-0.99, no threshold >50% BUY WR | 2026-06-25 |
| Rolling window stabilizes BUY direction | Rolling 252 increases BUY predictions, worsens accuracy | 2026-06-25 |
| Label inversion reorients BUY signal | EURAUD label-inversion test: 22.7%→31.0%, still <50% | 2026-06-25 |
| Carry feature causes BUY inversion (CHF cluster) | Walk-forward counterfactual ablation | 2026-06-20 |
| DXY feature causes BUY inversion (equity cluster) | Walk-forward counterfactual ablation | 2026-06-20 |
| Ensemble corrects directional flip | Walk-forward comparison, sign test p=0.17 | 2026-06-19 |

## What Would Reopen Investigation

- A new feature group is added and walk-forward shows BUY WR > 50% for at least 1 SELL_ONLY asset
- Label structure is changed (e.g., trend-adjusted barriers, multi-class labels) and symmetry test passes
- Regime-conditional model is rebuilt with different architecture (e.g., LSTM, transformer) and outperforms baseline BUY WR
- At least 500 additional OOS trading days accumulate and the BUY WR trend is improving (>50% in most recent fold)
