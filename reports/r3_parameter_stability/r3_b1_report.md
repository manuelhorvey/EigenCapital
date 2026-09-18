# R3-B1 — Parameter Stability Grid (OBSERVED report)

**Experiment:** R3-B1 parameter stability grid  
**Contract:** `docs/research/R3_PARAMETER_STABILITY.md` (preregistered; pre-execution addendum frozen)  
**Run:** 2026-09-17T14:42:18.566332+00:00 · 56.0s · 14 workers · deterministic (no RNG)  
**Data:** 8 symbols (r4_local_v1): AUDUSDm, EURUSDm, GBPUSDm, NZDUSDm, USDCADm, USDCHFm, USDJPYm, XAUUSDm  
**Costs:** 15.0 bps one-way, identical across points  
**Grid:** 1500 points, full factorial — 5×4×5×5×3

> **What this study is:** a robustness study of the FROZEN R4
> configuration under preregistered bounded perturbations.
> **What this study is NOT:** a parameter search. Nothing here
> recommends parameters; nothing here modifies production R4.

## Verdict (preregistered F1/F2)

**Outcome: OUTSIDE_STABLE_REGION**

> the frozen configuration itself classifies as FRAGILE on this data (preregistered thresholds); all its immediate grid neighbours are also FRAGILE — no recommendation is made.

## Frozen center configuration

| Axis | Frozen value |
|---|---|
| signal_lookback_long | 252 |
| skip_months ×21 | 21 |
| vol_lookback_signal | 60 |
| risk_lookback | 20 |
| rebalance_every | 5 |

Center classification: **FRAGILE** · full-path Sharpe -0.245 · max DD 6.37% · 1311 trades

## Region machinery

- Component reachable from the center through adjacent non-FRAGILE points: **0** of 1500
- STABLE fraction within the component (preregistered rule): **0.000** (stable —)
- Center adjacent to at least one FRAGILE point: **True**

## Axis-level association (one Holm family, preregistered)

| Axis | Spearman ρ | t | raw p | Holm p | flagged ≤0.05 |
|---|---|---|---|---|---|
| signal_lookback_long | +0.380 | +15.88 | 0.0000 | 0.0000 | YES |
| skip_months ×21 | +0.231 | +9.17 | 0.0000 | 0.0000 | YES |
| vol_lookback_signal | +0.163 | +6.39 | 0.0000 | 0.0000 | YES |
| risk_lookback | +0.587 | +28.07 | 0.0000 | 0.0000 | YES |
| rebalance_every | +0.000 | +0.00 | 1.0000 | 1.0000 | no |

Point classifications across the full grid: FRAGILE 1380 · NON_FRAGILE 120

## False-confidence diagnostics

- **PBO:** 1.0000 over 1500 candidates (0 points excluded — WF geometry cannot fit)
  - grid points share the same underlying data — trials are not independent; PBO is a false-confidence diagnostic, never a calibrated probability
- **Deflated Sharpe:** DSR 0.0019 (SR0 = 0.0478, n_trials = 1500)
  - grid points share the same underlying data — the effective number of independent trials is below 1,500; DSR reported as a diagnostic, used for no decision

## Interpretation guards (frozen)

- Region statements are about THIS data and THIS preregistered grid only.
- The WF aggregate is a per-point diagnostic, never a selection score.
- No pass/fail threshold beyond the preregistered F1/F2 criteria applies.
- No output of this study is a parameter recommendation; the frozen R4
  specification remains untouched.

*Errors: 0 · Records: 1500 · Deterministic rerun: identical.*
