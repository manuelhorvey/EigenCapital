# Modes Domain — capital, risk, and concurrency presets

Predefined mode configurations that set capital, max concurrent positions, factor exposure limits, and drawdown limits for different environments.

| File | Purpose |
|------|---------|
| `configs/domains/modes/production.yaml` | Paper trading (22-asset, 13 concurrent, -15% DD, $100K capital) |
| `configs/domains/modes/live.yaml` | Live funded account (6 concurrent, -10% DD, $100K capital) |
| `configs/domains/modes/challenge_ftmo_10k.yaml` | FTMO 10K challenge (5 concurrent, -8% DD, $10K capital) |

Mode selection via `configs/paper_trading.yaml:mode:`. The selected mode's `defaults` block is merged into the global config at startup by `configs/paper_config_registry.py`. Mode overrides are the outermost layer — they can be further overridden by per-asset YAML files.
