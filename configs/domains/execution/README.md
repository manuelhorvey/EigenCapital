# Execution Domain — spread gate, session gate

Live-entry gating parameters.

| File | Purpose |
|------|---------|
| `spreads.yaml` | Spread gate — tiers (fx_major: 10bps, fx_cross: 20bps, indices: 15bps, metals: 20bps), staleness timeout, observe-cycle warmup
| `sessions.yaml` | Session gate — UTC hour windows per tier (fx: 7–17, indices: 13–20, crypto: 0–24)

Both gates are wired through `decision_pipeline.py` as pipeline stages.
The spread gate blocks entries when live spread exceeds the tier's threshold;
the session gate blocks entries outside the tier's UTC window.

Crypto tier (0–24) enables 24/7 trading for BTCUSD and similar assets.
See `paper_trading/execution/decision_pipeline.py:apply_spread_gate()` and
`apply_session_gate()`.
