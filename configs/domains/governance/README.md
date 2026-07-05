# Governance Domain — regime geometry, liquidity, narrative

Secondary gates that adjust SL/TP and position sizes outside the core pipeline.

| File | Purpose |
|------|---------|
| `regime_geometry.yaml` | Per-regime SL/TP multipliers (`GREEN`/`YELLOW`/`RED`) — currently all 1.0x (neutral)
| `liquidity.yaml` | Liquidity-regime detector — volume Z-score thresholds, Amihud illiquidity ratios, thin/stressed SL widen and size reduce
| `narrative.yaml` | FXStreet narrative ingestion — geopolitical SL widen, risk-off size reduce, auto-confirm deadline

Liquidity regime states: NORMAL → THIN (soft warning, SL widen 15%) →
STRESSED (halt + 30% SL widen). Note: only STRESSED halts; THIN routes to
soft warnings per the 2026-06-17 fix.
