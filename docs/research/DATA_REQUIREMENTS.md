# Data Requirements — Prerequisites for Reopening R7 and R4-MR

**Status:** DRAFT — a contract document, NOT a preregistration and NOT a trial slot. No experiment may cite this document as authorization to run.
**Date:** 2026-09-17
**HEAD at drafting:** 0b297a9 (research program R0–R6 closed; queue CLOSED)
**Governing documents:** [RESEARCH_PROGRAM_STATUS.md](RESEARCH_PROGRAM_STATUS.md) (reopening rules 1–2) · [R4_MEAN_REVERSION.md](R4_MEAN_REVERSION.md) (B2 parking rule: "reopening requires a material data upgrade… a new data class, not more attempts on the same wall") · [R5_TRIPLE_BARRIER.md](R5_TRIPLE_BARRIER.md) (event/PIT precedents)

---

## 0. Purpose and non-goals

This document defines WHAT data would constitute a material upgrade, and the
quality/contract bar it must meet BEFORE any new preregistration is drafted.
It exists so that a future reopening starts from requirements instead of
enthusiasm — and so that nobody manufactures fake proxies to satisfy a
research idea (the explicit R7 lesson: "do not implement fake proxies merely
to satisfy a research idea"; OHLC-derived pseudo order-flow is banned).

Non-goals: no trial slots are opened here; no pipeline code is written
against future data; no vendor is selected; no production path is touched.

---

## 1. The global data contract (applies to ANY new data class)

Every dataset proposed for research reopening must satisfy all of the
following, verified in an R0-style verification pass BEFORE a new
preregistration is written:

1. **Point-in-time integrity** — every record carries a real event timestamp
   with documented clock source and any settlement/correction latency; no
   restatements without an explicit, queryable revision channel.
2. **Persisted provenance** — a frozen manifest in the `R5_data_manifest.json`
   pattern: per-file SHA-256 prefixes, row counts, first/last timestamps,
   capture date, vendor/licence note, and a combined hash. Any change to the
   data invalidates the manifest and any preregistration that cited it.
3. **Versioned universe** — instruments, sessions, and any filtering rules
   frozen under a version id (`<family>_v<n>`) before first use.
4. **Sufficient history** — enough depth to support the frozen validation
   geometry (train 750 / test 250 / purge 10 / embargo 5, anchored — the
   `parameter_stability.grid` constants) plus an OOS region, across multiple
   regime episodes. As a floor: ≥ 2 years for intraday classes, ≥ 3 years
   preferred.
5. **Quality gates, exclusion-not-imputation** — gap/correction counts,
   duplicate-timestamp checks, and dead-session handling defined up front;
   defective data is EXCLUDED and counted, never imputed or forward-filled
   into silence.
6. **Storage + access** — local columnar/CSV layout with a deterministic
   loader; the same bytes must be re-readable byte-identically (R5's
   determinism discipline extends to data loading).

---

## 2. R7 — Order-Flow Entropy (currently BLOCKED — DATA)

R7's blocker is precise: the entropy methodology requires a trade/quote
sequence, and EigenCapital's local data is D1 OHLC only. The article's own
conclusions demand aggregated trades, a fixed ring buffer, and activity
thresholds — none constructible from bars.

### 2.1 Required fields (minimum viable)

Per trade print or aggregate, one record with:

```text
instrument            symbol, versioned-universe member
trade_timestamp       exchange event time (ms or better)
price                 last trade price
size                  contracts/lots
aggressor_side        BUY | SELL   (the load-bearing field)
bid_price / ask_price optional but strongly preferred
bid_size / ask_size   optional but strongly preferred
```

**Non-negotiable:** `aggressor_side` (or an equivalent, documented,
point-in-time trade-direction classification). Entropy rate estimation needs
the up/down tick sequence of *signed* activity; OHLC cannot produce it, and
a heuristic guess at direction would produce synthetic sophistication —
exactly what the frozen R7 assessment bans.

### 2.2 Granularity and history

- **Granularity:** every trade, or time/volume-bar aggregates at ≤ 1 minute
  for the most active sessions. Aggregation scheme must itself be frozen
  before preregistration.
- **History:** ≥ 12 months of continuous sessions for the candidate
  instruments (enough to train/validate the EMA smoothing + hysteresis
  behaviour through several volatility regimes), 24 months preferred.
- **Instruments:** start from instruments actually traded by the platform
  (the D1 universe); expanding the instrument set is part of the new
  preregistration, not the data acquisition.

### 2.3 Quality gates specific to R7

- Session calendar coverage ≥ 99% of expected sessions per instrument.
- Timestamp monotonicity enforced; duplicate prints flagged and excluded.
- Aggressor-side coverage ≥ 95% of prints (below that, the entropy rate is
  measurement, not inference — the shortfall is reported, never filled).
- A declared concurrent-quote policy: if quotes are supplied, their latency
  relative to trades must be documented (stale-quote contamination would
  silently leak future information into "current" book state).

### 2.4 What R7 becomes with this data (preview only — NOT a preregistration)

The frozen R7 architecture applies unchanged: ring buffer → 2×2 transition
counts → Shannon entropy rate → stationary distribution → EMA smoothing →
hysteresis bands → minimum-activity threshold → regime classification,
compared against the existing regime gate as

```text
R4  vs  R4 + existing regime gate  vs  R4 + entropy gate
```

with entropy as infrastructure/gating, never alpha. Falsification criterion
carried over from the frozen queue: entropy does not classify regimes
differently from the existing gate, or worsens OOS performance when applied.

---

## 3. R4-MR — Mean-Reversion / Stat-Arb (currently PARKED)

R4's parking rule names the blocker class precisely: daily bars cannot
satisfy the joint ADF ∧ cointegration p<0.05 ∧ half-life∈[5,60] gates often
enough (0–3 active regimes per ~87 estimation dates; 5 trades in 8 pairs).
The evidence standard stays frozen; the DATA CLASS changes.

### 3.1 Required granularity (either satisfies "new data class")

- **Intraday bars:** ≤ 1-hour bars for the candidate pairs, ≥ 2 years
  (≥ 3 preferred). This multiplies estimation windows by ~7–24× versus D1
  and makes the 250-bar rolling window responsive to genuine relationship
  changes rather than to years-long drift.
- **Intraday bars + session calendar:** with half-session alignment rules
  frozen up front (crypto vs FX vs index futures sessions differ materially).

### 3.2 Required fields per bar

```text
instrument, bar_timestamp (session-aligned, tz-declared),
open, high, low, close, volume
```

FX/CFD candidates (EURUSD, GBPUSD, AUDUSD, NZDUSD, USDCHF, USDCAD, USDJPY,
XAU, XAG) plus the index/crypto pairs already declared in the frozen B2
universe. No new pairs without declared economic rationale in the new
preregistration.

### 3.3 Quality gates specific to R4-MR

- Bar integrity: no missing OHLC, high ≥ max(open, close), low ≤
  min(open, close); violations excluded-and-counted.
- Session-continuity metadata so that weekend/session gaps do not silently
  enter the 250-bar rolling windows (the PIT estimation window counts
  *bars*, and bar boundaries must be session-true).
- The 2020-01 → 2026-08 D1 history must remain available unchanged for
  continuity diagnostics against the parked B1/B2 results.

### 3.4 What reopens (preview only — NOT a preregistration)

The frozen pipeline (`estimation.py` / `pipeline.py`) is data-class agnostic
by construction: rolling ADF → cointegration → hedge ratio → half-life →
z-score entries/exits → costs → WF. Reopening means: new universe version,
the SAME gates re-exercised on intraday bars, the SAME cost model per new
bar economics (re-declared in the preregistration), the SAME falsification
arms and parking rule logic. If the expanded evidence class still starves
the gates, the family closes permanently — that would be the second and
final wall.

---

## 4. Explicitly banned (both tracks)

- OHLC-derived pseudo order-flow, fake trade-direction proxies, or
  synthetic microstructure of any kind.
- Starting implementation before a manifest-frozen, verification-passed
  dataset exists (no "build it and the data will come").
- Reusing consumed trial slots: R7 and R4-MR reopenings each get fresh
  preregistrations and fresh slot ids.
- Any silent relaxation of the R4-MR gates or the R7 architecture to
  accommodate whatever data eventually arrives. The data must meet the
  spec; the spec does not bend to the data.

---

## 5. Reopening flow (when data arrives)

```text
1. DATA ACQUISITION      vendor/dump lands locally
2. MANIFEST FREEZE       R5-pattern manifest, combined hash, capture date
3. R0-STYLE VERIFICATION fields/coverage/quality gates → PASS table per §1
4. NEW PREREGISTRATION   declared rationale, universe version, frozen spec,
                         fresh trial slot id, falsification criteria
5. LEDGER OPENED         new stage doc (e.g. R7-B1 / R4-B3), BEFORE code
6. THEN — and only then — implementation
```

Steps 1–3 are engineering, not research: they open no trial slots and
commit to no hypothesis. The preregistration boundary is crossed only at
step 4.
