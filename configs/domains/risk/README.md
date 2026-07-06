# Risk Domain — capital, halt, sizing, exits

Operator-write surface for all risk-related configuration. Phase 12 fully
promoted; these files are the source of truth (not the legacy YAML).

| File | Purpose |
|------|---------|
| `configs/domains/risk/capital.yaml` | Initial capital (`100000`), position_size (`0.95`), portfolio drawdown limit (`-0.15`)
| `configs/domains/risk/halt.yaml` | Circuit-breaker thresholds — drawdown, monthly PF, signal drought, probability drift
| `configs/domains/risk/sizing.yaml` | 28 position-sizing guardrails — per-position caps, risk per trade, drawdown taper, MT5 leverage
| `configs/domains/risk/exits.yaml` | Adaptive-exit defaults — trailing retrace (`0.33`), BE lock (`0.5R`), time decay

**Edit these files**, then run `config_mirror_legacy.py --write` to regenerate
the legacy mirror. Deleting a key from a domain file restores the typed
Python default from `configs/domain_models/risk.py`.
