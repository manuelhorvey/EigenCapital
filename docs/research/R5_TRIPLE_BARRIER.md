# R5 — Triple-Barrier Labeling (Label Quality First)

**Date:** 2026-09-17
**Branch:** main
**HEAD:** 0b297a9
**Governing documents:** [RESEARCH_LITERATURE_AUDIT_REVIEW.md](RESEARCH_LITERATURE_AUDIT_REVIEW.md) (review §"R5 — Triple Barrier": labels first, no ML, no barrier sweeps) · [R0_INFRASTRUCTURE_VERIFICATION.md](R0_INFRASTRUCTURE_VERIFICATION.md)

---

## R5-A: infrastructure verification (contract BEFORE code)

| Component | Verdict | Evidence |
|---|---|---|
| Entry events | **PASS — reuse** | `simulate_portfolio` (`export_r4_trade_stream.py`) emits strictly-alternating fills per symbol; every OPEN fill is a complete entry event (timestamp, side, fill_price, instrument). Each frozen-config run is deterministic. |
| Point-in-time volatility | **PASS — reuse** | `compute_r4_signal` already computes per-symbol 60-day realized vol (`rolling(60).std() * sqrt(252)`), shifted PIT by the pipeline's one-bar convention. The labeler REUSES this series unchanged. |
| Sample uniqueness | **GAP → implement in R5-B** (corrected before any code — the R5-A draft wrongly claimed reuse) | the platform's uniqueness presence is awareness-level only: purging/embargo of label overlap in `walk_forward.py`, non-overlapping blocks in `block_bootstrap.py`. NO AFML average-uniqueness/concurrency module exists. Per-event concurrency and average uniqueness are simple, pure computations and will be implemented inside the R5-B diagnostics module with hand-computed tests. |
| Existing triple-barrier code | **NONE** | repo-wide grep: zero triple-barrier / first-touch / vertical-barrier implementations. The labeler is genuinely new code (the one permitted R5-B module). |
| `TradeStream` schema | **PASS — reuse** | R1 persistence for provenance discipline; not consumed by R5-B except as precedent. |

**Conclusion:** the only genuinely new code for R5 is the **labeling engine
itself** (first-touch barrier resolution) plus its diagnostics. No statistical
machinery is forked; no volume/price source other than the frozen replica's
bars.

---

## R5-A: frozen research contract

### 1. Event definition (the single most important clause)

An **event** is one entry fill (OPEN side) of the frozen-R4 replica pipeline
(`simulate_portfolio` under `configs/production/config.toml`). Concretely:
an event is a tuple

```text
event_id
instrument
decision_timestamp   (the weight-date that produced the entry)
event_timestamp      (the fill/entry bar timestamp = next trading day)
side                 (LONG | SHORT, from the fill)
entry_price          (the fill price: next-bar open)
```

Events are recorded with per-event PIT metadata and are never re-derived
after the fact. Labels are attached to *events*, not to arbitrary bars.

### 2. The ONE preregistered labeling specification (no sweeps, ever, in R5)

Exactly one specification is evaluated. All values are frozen here, before
any label is computed:

```text
volatility            : per-symbol 60-day realized vol of daily close returns,
                        annualized (sqrt 252), computed on data up to and
                        including the event's PREVIOUS bar (strict PIT; no
                        exception path — reuse of the replica's own shifted
                        series satisfies this by construction)
pt_multiplier         : 2.0   (profit-take barrier  = entry ± 2.0 * daily_vol * entry_price)
sl_multiplier         : 2.0   (stop-loss barrier     = entry ∓ 2.0 * daily_vol * entry_price)
vertical_horizon      : 10 trading bars after the event bar (inclusive scan window)
first-touch rule      : scan bars event_timestamp+1 .. +10; the FIRST bar whose
                        high/low touches its barrier wins; ties (both barriers
                        in one bar) resolve by WHICH PRICE LEVEL is closer to
                        the open of that bar; if none touch → vertical-barrier
                        label from the close at bar +10
side handling         : LONG and SHORT events are labeled symmetrically
                        (barriers mirror; the label semantics below already
                        encode direction)
```

**Banned:** any search over PT/SL multipliers, horizons, or barrier styles.
A barrier-sensitivity study, if ever wanted, is a separately preregistered
experiment (R5-C), not part of R5.

### 3. Label semantics

Per event, the label is one of:

```text
+1 : profit-take barrier touched first
-1 : stop-loss barrier touched first
 0 : vertical barrier expiry at bar +10, labeled sign(close(+10) − entry_price)
     from the event's own perspective (LONG: sign of close − entry;
     SHORT: sign of entry − close — the mirror); exact equality → 0.
     Costs are NOT part of labeling.
```

The recorded result per event carries BOTH the label and the full first-touch
evidence:

```text
event_id, instrument, side, event_timestamp, entry_price,
vol_observation_timestamp, daily_vol, pt_price, sl_price,
vertical_deadline, first_touch_timestamp, first_touch_type
(PT | SL | VERTICAL), first_touch_price, label, label_path (the
high/low/close path used, for audit)
```

### 4. The PIT invariant (no exception path)

```text
every input to barrier construction (vol, barriers, horizon) must be a
function of data available at or before event_timestamp
```

The scan window itself is future data — that is the *definition* of a label,
not a violation; labels are training targets, never features. The vol
estimate is the only quantity that must be PIT, and it is enforced by
reusing the replica's shifted series (violation → hard error, mirroring the
R2 factor-lab contract).

### 5. Diagnostics (measurement, not optimization)

The R5-B study reports, for the frozen spec on the frozen replica events:

1. **Label distribution** — counts/proportions of {+1, −1, 0}.
2. **First-touch type distribution** — PT / SL / VERTICAL.
3. **Time-to-touch distribution** — bars until first touch, by type.
4. **Overlap structure** — for every pair of events on the same instrument
   whose [event, first_touch] intervals intersect: count, average overlap
   length, and the per-event overlap count.
5. **Sample uniqueness** — per-event average uniqueness from concurrency:
   for each event, let c_t = number of overlapping event intervals
   [event, first_touch] on the same instrument covering bar t; the event's
   average uniqueness is mean(1/c_t) over its interval. Implemented fresh
   in R5-B (see corrected verification table) with hand-computed tests.
6. **Determinism** — two runs of the labeler on the same inputs are
   byte-identical.

### 6. Explicit non-goals (frozen)

- **R5 establishes label validity and behavior, NOT predictive power.** A
  balanced label distribution proves nothing about predictability; an
  imbalanced one does not indict the instrument.
- No classifier, no ML, no feature engineering, no take/skip/size logic.
- No comparison of label distributions across barrier specifications
  (that is a banned sweep).
- No alteration to the frozen R4 production strategy or the replica
  pipeline (events are READ from it, never modified).

### 7. Falsification criteria for R5-B

- F1: any first-touch resolution that contradicts a hand-computed case →
  the labeler is defective → fix and re-run (same preregistration, F3
  discipline).
- F2: PIT violation detected (vol uses data after the event bar) → result
  discarded, defect fixed, re-run.
- F3: non-determinism across runs → result discarded, defect fixed, re-run.
- F4: any event whose PIT vol estimate is unavailable (insufficient
  history before the event bar) is EXCLUDED and counted — never imputed;
  the exclusion count is reported as evidence.

### 8. Trial accounting and scope

- ONE preregistered trial slot (R5-B) for the frozen specification.
- R6 (meta-labeling) is gated on R5 producing validated label *structure*,
  and even then begins with label diagnostics, not a model.
- Scope guard: research-only; nothing here touches R4 production, the risk
  engine, or execution.

---

## R5-B status: COMPLETE — measurement study delivered (2026-09-17)

**Execution:** `scripts/run_r5_b1_labels.py` — entry events extracted from
the frozen-R4 replica (`simulate_portfolio` OPEN fills, exactly the pipeline
that produced TS-R4-D1-0001), labeled with the ONE frozen specification.
Zero modifications to the replica or to any production path.

**Population:** 1,311 events across 8 instruments — matches the R1 trade
stream exactly (independent cross-check that the event definition is the
replica's true entry sequence). 0 exclusions; every event had sufficient PIT
history and a full 10-bar scan window.

**Observed instrument behavior (frozen diagnostics, contract item 5):**

| Diagnostic | Value |
|---|---|
| First touches | PT 624 · SL 584 · VERTICAL 103 |
| Labels | +1 = 681 (624 PT + 57 favorable verticals) · −1 = 630 (584 SL + 46 adverse verticals) · 0 = 0 |
| Time-to-touch (PT/SL) | mean 3.39 bars · max 10 (n = 1,208) |
| Overlap | 492 overlapping pairs · 663 events with ≥1 overlap · max 4 on one event |
| Average uniqueness | mean 0.837 · min 0.389 · max 1.0 |

Per-instrument notes (OBSERVED, not interpreted): XAUUSD the most PT-skewed
(+108/−59); USDCHF the most SL-skewed (+77/−96). No per-instrument action is
implied or permitted by this study.

**Correctness arms (F1–F4): none fired.**
- F1: 20 unit tests including exact hand-computed first-touch cases (PT
  first, SL first, same-bar double-touch tie rule, SHORT mirroring,
  event-bar-never-scanned) — all pass.
- F2: no PIT violation; the vol series is the replica's own shifted 60-day
  construction (PIT by construction), and the vol window provably excludes
  the event bar (test: perturbing the event bar and everything after does
  not move the vol).
- F3: determinism verified byte-identical.
- F4: exclusion-and-count policy implemented and tested; exercised 0 times
  on real data.

**Interpretation guards (frozen):**
- The near-symmetric PT/SL split is the EXPECTED behavior of symmetric
  ±2σ barriers — it confirms the instrument behaves as constructed and
  says nothing about predictability or strategy quality.
- Label balance/imbalance is not evidence of anything beyond instrument
  behavior (contract item 6). R5 establishes label validity and behavior,
  NOT predictive power.
- Vertical expiries resolving to ±1 by sign (label 0 requires exact
  close==entry equality, which never occurred on daily closes) is observed
  instrument behavior under the frozen semantics, recorded openly.
- ONE preregistered trial slot consumed. Barrier sweeps remain banned; any
  sensitivity study is a NEW preregistration (R5-C).

**Infrastructure corrections made during R5-B (all before the real run or
openly recorded):**
1. The R5-A verification table initially claimed sample-uniqueness REUSE —
   inspection showed awareness-level presence only; corrected to an
   implemented-fresh GAP before any code was written.
2. The engine initially computed ABSOLUTE barrier distances; the frozen
   ledger formula is multiplicative (entry ± m·σ_d·entry). Caught against
   the ledger before the real run; the test suite pins the multiplicative
   formula.
3. Post-run artifact honesty fix: label-distribution keys renamed to state
   that +1/−1 include sign-resolved vertical expiries.

**R5 status: A ✅ · B ✅ — COMPLETE / FROZEN.** The labeling instrument is
validated and characterized. R6 (meta-labeling) remains gated on the frozen
queue: it would begin from label diagnostics and a baseline hierarchy
(R4 → deterministic filter → logistic regression → …), never a direct ML
jump, and every stage would consume exactly one trial slot.
