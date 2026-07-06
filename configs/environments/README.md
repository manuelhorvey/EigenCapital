# Environment Overlays — paper / live / backtest / research

Runtime environment profiles that override domain defaults for specific
deployment contexts.

| File | Purpose |
|------|---------|
| `configs/environments/paper.yaml` | Live paper-trading default — `data_source: mt5`, `research_mode: false`, `rebalance: daily`
| `configs/environments/live.yaml` | Live-trading profile (isolates from accidental paper-data execution)
| `configs/environments/backtest.yaml` | Backtesting profile — may override data_source, rebalance frequency
| `configs/environments/research.yaml` | Research profile — may enable research_mode, use yfinance fallback

The active environment is resolved by `EIGENCAPITAL_ENV` env var or the `mode:`
selector, falling back to `"paper"`. A dedicated environment resolver
(`configs/environment_resolver.py` — planned, Phase 13, not yet implemented) will centralise this
resolution logic.

Each environment file is a partial overlay — only the keys you want to override
need to be present. The compose order (see `configs/README.md`) ensures that
environment files override domain defaults but are overridden by per-asset files
and mode selectors.
