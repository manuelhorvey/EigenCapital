# Portfolio Domain — weight strategy, factor model

Portfolio-wide allocation method and factor exposure limits.

| File | Purpose |
|------|---------|
| `weights.yaml` | `weight_method` selector (currently `factor_constrained_v2`) and `factor_exposure_limits` per group (CHF, US_EQUITY, AUD, NZD, etc.)

The factor-constrained weight optimiser uses hard linear inequality constraints
(not penalty terms) to enforce per-group exposure limits. See
`shared/factor_model.py` for the implementation.
