# R5-B — Triple-Barrier Label Quality (OBSERVED report)

**Experiment:** R5-B triple-barrier label-quality measurement  
**Contract:** `docs/research/R5_TRIPLE_BARRIER.md (frozen before code)`  
**Run:** 2026-09-17T23:29:58.341945+00:00 · spec `r5_spec_v1` (ONE preregistered specification)  
**Spec:** PT 2.0 / SL 2.0 · vertical 10 bars · vol 60d PIT · multiplicative: entry ± m · daily_vol · entry_price

> **What this is:** a measurement of what the frozen labeling
> specification produces on the frozen replica's entry events.
> **What this is NOT:** evidence of predictive power, a model input
> study, or a barrier-specification comparison. Label distribution
> balance proves nothing about predictability (frozen contract item 6).

## Events

- 1311 entry events from the frozen-R4 replica pipeline
- 1311 labeled · 0 excluded (never imputed): {}

## Label distribution (valid events)

- **+1** (PT first, or vertical expiry with close favorable to the event): 681
- **−1** (SL first, or adverse vertical expiry): 630
- **0** (vertical expiry, close == entry exactly): 0

Note: 103 vertical expiries resolved to ±1 by the sign of the close-vs-entry move; exact equality never occurred on daily closes, so no label 0 was produced. This is observed instrument behavior, not a defect (the ledger's label semantics are sign-based with 0 only on exact equality).

## First-touch types

- PT: 624 · SL: 584 · VERTICAL: 103
- time-to-touch (PT/SL): n=1208, mean=3.39 bars, max=10 bars

## Overlap structure

- overlapping event pairs: 492
- events with ≥1 overlap: 663
- max overlaps on a single event: 4

## Sample uniqueness (concurrency-based, implemented for R5)

- mean: 0.8371 · min: 0.3889 · max: 1.0

## Per instrument

| Instrument | events | excluded | +1 | −1 | 0 | PT | SL | VERT | mean uniq |
|---|---|---|---|---|---|---|---|---|---|
| AUDUSDm | 167 | 0 | 84 | 83 | 0 | 78 | 77 | 12 | 0.845 |
| EURUSDm | 167 | 0 | 86 | 81 | 0 | 80 | 71 | 16 | 0.84 |
| GBPUSDm | 152 | 0 | 75 | 77 | 0 | 69 | 72 | 11 | 0.85 |
| NZDUSDm | 151 | 0 | 73 | 78 | 0 | 68 | 76 | 7 | 0.847 |
| USDCADm | 167 | 0 | 82 | 85 | 0 | 75 | 82 | 10 | 0.837 |
| USDCHFm | 173 | 0 | 77 | 96 | 0 | 73 | 82 | 18 | 0.814 |
| USDJPYm | 167 | 0 | 96 | 71 | 0 | 84 | 68 | 15 | 0.828 |
| XAUUSDm | 167 | 0 | 108 | 59 | 0 | 97 | 56 | 14 | 0.838 |

## Interpretation guards (frozen)

- These are properties of the MEASUREMENT INSTRUMENT on this dataset —
  not a strategy signal and not a forecast.
- ONE preregistered trial slot (R5-B) consumed; barrier sweeps are
  banned; a sensitivity study would be a NEW preregistration (R5-C).
- No classifier or meta-model is built here; R6 is gated on R5's
  label-structure evidence, not on this report's balance.
- Research-only: events are read from the replica; R4 production is
  untouched.

*Artifacts: r5_labels.json, r5_labels.csv (per-event audit trail), r5_labels.md in reports/r5_triple_barrier/.*
