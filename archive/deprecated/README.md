# Deprecated Modules

These modules are no longer used in production code. They are kept for backward
compatibility with historical scripts and tests.  New code MUST NOT import from
these modules.

| Module | Replaced By | Deprecated |
|--------|-------------|------------|
| `features.builder` | `features.alpha_features.build_alpha_features` | 2026-07-01 |
| `features.pair_specific` | `features.alpha_features` | 2026-07-01 |
| `features.labels` | `labels.compat` (legacy) or `labels.triple_barrier` | 2026-07-01 |
| `features.cot_features` | Removed (zero gain across all 22 assets) | 2026-07-09 |
| `features.divergence` | Integrated into `features.alpha_features` | 2026-06-15 |
| `signals.simple_threshold` | `paper_trading.inference.pipeline.run_decision_pipeline` | 2026-06-01 |
| `signals.alpha_weighting` | Ensemble disabled (ADR-026); `base_weight=1.0` | 2026-06-20 |
| `risk.position_sizing` | `paper_trading.entry.EntryService` | 2026-06-01 |
| `risk.drawdown_controls` | `paper_trading.governance.drawdown_controls` | 2026-06-01 |

## Removal Schedule

These modules will be removed in a future major release (v4.0+).
