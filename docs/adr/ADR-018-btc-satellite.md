# ADR-018: BTC Satellite Isolation With Regime Gate (NOT IMPLEMENTED)

**Status:** Accepted (proposal accepted; implementation deferred indefinitely)

**Date:** 2026-05

## Context

BTC-USD was evaluated as a satellite asset for the EigenCapital portfolio. As a
non-traditional asset with different market microstructure (24/7 trading, no
correlation bounds, different liquidity profile), a satellite architecture was
proposed: BTC would trade under an isolated regime gate separate from the main
portfolio governance.

## Decision

Accepted in principle, but never implemented. BTC-USD was removed from the asset
universe during portfolio rationalization (2026-06-20) before deployment. The
BTC satellite concept is effectively superseded by the removal decision.

## Rationale for Removal

BTC-USD was part of the initial 22-asset portfolio but was removed along with
AUDNZD, EURUSD, and AUDCHF during the June 2026 diagnostic chain. No BTC-specific
model exists in production. BTC was never deployed in any live paper trading
environment.

## Key References

- ADR-012: Three-asset portfolio (historical — included BTC)
- `AGENTS.md`: Portfolio removal timeline (2026-06-20)
- `scripts/restoration/`: Asset restoration framework (BTC not listed)
