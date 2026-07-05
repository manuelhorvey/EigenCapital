# Environment Overlays — paper / live / backtest / research

Runtime environment profiles that override domain defaults for specific
deployment contexts.

| File | Purpose |
|------|---------|
| `paper.yaml` | Live paper-trading default — `data_source: mt5`, `research_mode: false`, `rebalance: daily`
| `live.yaml` | Live-trading profile (isolates from accidental paper-data execution)
| `backtest.yaml` | Backtesting profile — may override data_source, rebalance frequency
| `research.yaml` | Research profile — may enable research_mode, use yfinance fallback

The active environment is resolved by `EIGENCAPITAL_ENV` env var or the `mode:`
selector, falling back to `"paper"`. A dedicated environment resolver
(`configs/environment_resolver.py` — planned, Phase 13) will centralise this
resolution logic.

Each environment file is a partial overlay — only the keys you want to override
need to be present. The compose order (see `configs/README.md`) ensures that
environment files override domain defaults but are overridden by per-asset files
and mode selectors.
