# Operating Modes

EigenCapital ships three operating mode presets selected by `mode:` in the
configuration system. Mode definitions live in per-file YAML files under
`configs/domains/modes/`. Top-level defaults serve as the base config;
mode-specific overrides merge on top.

```yaml
# configs/domains/modes/production.yaml
mode: production     # active mode
description: "Standard paper trading"
capital: 100000
# ...
```

The active mode is the only source of truth at runtime; the inactive
modes are ignored.

## Mode Comparison Matrix

| Setting | production | challenge_ftmo_10k | live |
|---|---|---|---|
| `capital` | 100,000 | 10,000 | 100,000 |
| `portfolio_drawdown_limit` | −0.15 | −0.08 | −0.10 |
| `max_concurrent_positions` | 8 | 5 | 6 |
| `risk_per_trade_pct` | 0.02 | 0.01 | 0.01 |
| `max_risk_per_trade_pct` | 2.0 | 0.03 (≙ 3%) | 0.03 (≙ 3%) |
| `min_risk_per_trade_pct` | 0.001 | 0.001 | 0.002 |
| `max_daily_loss_pct` | 0.08 | 0.04 | 0.05 |
| **Factor exposure limits** | | | |
| &nbsp;&nbsp;`CHF` | 0.20 | 0.15 | 0.15 |
| &nbsp;&nbsp;`US_EQUITY` | 0.25 | 0.15 | 0.20 |
| &nbsp;&nbsp;`OIL` | 0.15 | 0.10 | 0.10 |
| &nbsp;&nbsp;`GOLD` | 0.15 | 0.10 | 0.10 |
| &nbsp;&nbsp;`AUD` | 0.25 | 0.20 | 0.20 |
| &nbsp;&nbsp;`NZD` | 0.25 | 0.20 | 0.20 |
| &nbsp;&nbsp;`JPY` | 0.25 | 0.20 | 0.20 |
| &nbsp;&nbsp;`FX_MAJOR` | 0.40 | 0.30 | 0.30 |
| &nbsp;&nbsp;`FX_CROSS` | 0.40 | 0.30 | 0.30 |
| &nbsp;&nbsp;`FX_COMMODITY` | 0.25 | 0.15 | 0.15 |

## Per-Mode Description

### `production`

Standard paper trading baseline:
- $100 K simulated capital.
- 8 concurrent positions max.
- Tighter DD ceiling (−15%) for research-grade exploration.

### `challenge_ftmo_10k`

FTMO 10K challenge variant:
- $10 K capital with 5% DD max (FTMO-style constraint).
- 5 concurrent positions.
- Tighter risk-per-trade (1%).
- Used for evaluation runs against FTMO challenge rules.

### `live`

Live funded account configuration:
- $100 K capital at the (real) broker.
- Tightest governance: 6 concurrent, 10% DD max.
- Risk-per-trade 1% with a higher `min_risk_per_trade_pct` (0.002) to
  suppress tiny paper-trade orders that would round to zero on real
  sizes.

## Selecting a Mode

```bash
# Create a new mode YAML
cp configs/domains/modes/production.yaml configs/domains/modes/my_new_mode.yaml
# Edit the file and change values, then:
./monitor_all
```

The mode is read at engine startup. Hot-swapping is not supported.

## Adding a New Mode

Create a new YAML file in `configs/domains/modes/` with the same structure
as the existing modes:
```yaml
description: "My custom mode"
capital: 50000
defaults:
  max_concurrent_positions: 4
  risk_per_trade_pct: 0.01
  max_daily_loss_pct: 0.05
  # ... all overrides
portfolio_drawdown_limit: -0.10
```

Then configure which mode is active via the environment overlay mechanism
or by editing the mode selector in the configuration.

The schema validator (`tools/check_config_schema.py`) enforces presence
of the required keys.

## Mode-Independent Defaults

The following live at the top level (apply to all modes):
- `position_size: 0.95`
- `rebalance: daily`
- `retrain_freq: annual`
- `retrain_window: 5`  (years of training history)
- `research_mode: false`
- `data_source: mt5`
- `portfolio.weight_method: factor_constrained_v2`
- `portfolio_drawdown_limit: -0.15`- Most `defaults.*` keys (churn ratio, cooldown half-life, profit-lock threshold, gate enablement, stacking block, leverage budget, spread tier map, session-hours tier map, etc.)

---

**Last updated:** 2026-07-05

