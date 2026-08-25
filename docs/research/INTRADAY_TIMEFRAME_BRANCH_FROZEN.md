# INTRADAY TIMEFRAME BRANCH — FROZEN

**Status:** 🔒 PERMANENTLY FROZEN as of 2026-08-24
**Scope:** Conventional OHLCV/session-based alpha research on bar timeframes
M1 → M5 → 15M → 30M → 1H, Exness 8-instrument universe.

This document is authoritative. Reopening any frozen campaign, re-tuning any
rejected hypothesis, or searching additional bar timeframes (2H/4H intraday,
45M/90M, etc.) without a **new pre-registered information-source rationale**
violates the EigenCapital falsification-first contract.

---

## Final scoreboard (127 hypotheses / evaluations)

| Timeframe | Campaign | Hypotheses | Supported | Verdict |
|---|---|---|---|---|
| M5 | 1 — price-based | 24 | 0 | ❌ Frozen |
| M5 | 2 — microstructure/volume proxies | 20 | 0 | ❌ Frozen |
| M1 | 3 — order-flow/liquidity proxies | 16 | 0 (1 fragile) | ❌ Frozen |
| 15M | 4 — multi-family discovery | 31 | 0 (10 fragile, 5 regime-dependent) | ❌ Frozen |
| 30M | 5 — mechanism-focused | 18 | **1** (ST-001) | 🟡 See below |
| 1H | 6 — ST-001 confirmation | 24 evals | 0 | ❌ Not confirmed |

## ST-001 disposition

`ST-001` (Asia→London transition continuation, 30M) is classified:

> **RESEARCH-SUPPORTED, TIMEFRAME-SPECIFIC, NOT VALIDATED.**

Evidence:
- Passed every frozen gate at 30M: net Sharpe +0.304, WF consistency 80%,
  permutation p = 0.020, adverse-cost resilient, DD −21%.
- Independent 1H confirmation on **8 years** of H1 data failed completely:
  all four primary horizons net-negative; no sensitivity variant survived
  Bonferroni family-wise correction (24 pre-registered evaluations).

Conclusion: the effect is an artifact of the 30M expression granularity and/or
the 2022–2026 sample window, not a general Asia→London continuation phenomenon.

**Prohibited:** further optimization of ST-001 (lookback, boundary, holding,
universe trimming), portfolio integration, fidelity-ladder entry.
It remains archived as forensic evidence only.

## What this freeze does NOT claim

The freeze does **not** claim "intraday doesn't work." It claims:

> In the Exness 8-instrument universe, conventional OHLCV/session-based
> information between M1 and 1H contains no robust exploitable alpha that
> survives hostile validation.

## Next branch (pre-registered direction)

New **information source**, not another timeframe sweep:
real broker tick data → broker-specific microstructure features
(signed tick flow, spread dynamics, quote intensity, price impact,
liquidity withdrawal). Explicitly labeled *broker-specific microstructure* —
Exness MT5 tick flow is not centralized institutional order flow.

Any survivor from that branch faces the same funnel: independent
confirmation → frozen configuration → paper fidelity → forward paper →
shadow → micro-live.
