# ADR-018: BTC Satellite Isolation With Regime Gate (NOT IMPLEMENTED)

**Status:** OBSOLETE 2026-07

**Date:** 2026-05

## Context

BTC-USD was evaluated as a satellite asset for the EigenCapital portfolio. As a
non-traditional asset with different market microstructure (24/7 trading, no
correlation bounds, different liquidity profile), a satellite architecture was
proposed: BTC would trade under an isolated regime gate separate from the main
portfolio governance.

## Decision

**OBSOLETE 2026-07** — BTC was never isolated as a satellite. It was briefly removed
during the June 2026 portfolio rationalization but was later restored and is now
actively traded as a full member of the 22-asset portfolio. The satellite isolation
architecture was never implemented and is no longer relevant.

## Current Status

BTCUSD is a permanent member of the 22-asset portfolio with a per-asset XGBoost model,
direction-conditional confidence thresholds, and standard governance pipeline (PEK
admission, adaptive exit, sizing guardrails). See `configs/domains/assets/` for
current configuration.

## Historical Context

The satellite proposal was evaluated in May 2026 but overtaken by events:
1. BTC was removed from trading June 2026-20 during the diagnostic chain
2. BTC was restored when the 22-asset portfolio was finalized
3. The portfolio governance (PEK, factor constraints, budget enforcement) handles
   BTC as a regular asset — no special satellite treatment is needed
