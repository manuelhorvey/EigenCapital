# ML Domain — calibration, ensemble, labels

Training and inference parameters for the ML pipeline.

| File | Purpose |
|------|---------|
| `configs/domains/ml/calibration.yaml` | Probability calibration method (`platt`), bin count, min samples per bin, model directory |
| `configs/domains/ml/ensemble.yaml` | Base/regime ensemble blend weights and threshold (currently inert — ensemble disabled per ADR-026) |
| `configs/domains/ml/kelly.yaml` | P2 fractional Kelly sizing — fraction (0.25), max_cap, min_edge |
| `configs/domains/ml/meta_labeling.yaml` | Meta-label confidence thresholds |
| `configs/domains/ml/shadow_models.yaml` | Shadow/canary model config — side-effect-free candidate comparison, logged to `data/live/shadow/` |
| `configs/domains/ml/triple_barrier.yaml` | Per-asset TP/SL multipliers for label generation (`pt`/`sl`/`vol_method`/`atr_period`) |

The triple-barrier file is the canonical source for label parameters, used by
`features/registry.py` and the training pipeline. It also archives REMOVED
assets (with `note:` annotations) for historical backtest reproducibility.

See `features/registry.py` and `labels/compat.py` for the pipeline that
consumes these parameters.
