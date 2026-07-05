# ML Domain — calibration, ensemble, labels

Training and inference parameters for the ML pipeline.

| File | Purpose |
|------|---------|
| `calibration.yaml` | Probability calibration method (`binned`), bin count, min samples per bin, model directory
| `ensemble.yaml` | Base/regime ensemble blend weights and threshold
| `meta_labeling.yaml` | Meta-label confidence thresholds
| `triple_barrier.yaml` | Per-asset TP/SL multipliers for label generation (`pt`/`sl`/`vol_method`/`atr_period`)

The triple-barrier file is the canonical source for label parameters, used by
`features/registry.py` and the training pipeline. It also archives REMOVED
assets (with `note:` annotations) for historical backtest reproducibility.

See `features/registry.py` and `features/labels.py` for the pipeline that
consumes these parameters.
