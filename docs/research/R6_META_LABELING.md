# R6 — Meta-Labeling (Baselines First)

**Date:** 2026-09-17
**Branch:** main
**HEAD:** 0b297a9
**Governing documents:** [RESEARCH_LITERATURE_AUDIT_REVIEW.md](RESEARCH_LITERATURE_AUDIT_REVIEW.md) (review §"R6": baseline hierarchy, incremental OOS evidence, ML on a leash) · [R5_TRIPLE_BARRIER.md](R5_TRIPLE_BARRIER.md) (event + label source, frozen)

---

## R6-A: infrastructure verification (contract BEFORE code)

| Component | Verdict | Evidence |
|---|---|---|
| Event population | **PASS — reuse** | R5's 1,311 events (cross-checked against TS-R4-D1-0001); labels from the frozen R5 spec. NO relabeling permitted. |
| Decision-time features | **PASS — replica internals** | `compute_r4_signal` produces, per (date, symbol): `sig` (12−1 momentum), `rk` (pct rank), `w` (centered rank → final weight), `regime` (PIT flag), `vol60`, `vol_scale`, plus market-level `avg_vol`. All are PIT by construction — the weights are computed FROM them, so availability = the decision bar. |
| Overlap-aware validation | **PASS — reuse** | `purged_walk_forward` (anchored, purge, embargo) with the frozen R3 geometry. R5's overlap finding (492 pairs, 663 events, max concurrency 4) makes random splits BANNED by design. |
| Uniqueness weights | **PASS — reuse** | R5-B's implemented-fresh concurrency/average-uniqueness module (tested, hand-computed cases). |
| Historical P&L per event | **PASS — derivable** | the replica's `trades_by_symbol` round-trips map 1:1 (chronologically, per symbol) onto entry fills; R6-B attaches realized net P&L by event_id with an order-correspondence test. |
| Existing meta-labeling code | **NONE** | repo-wide: no meta-label / take-skip implementations. Clean slate. |
| sklearn | **available (1.8.0)** | present in the environment; not currently a declared project dependency. Formal dependency addition is R6-B2's concern if B2 is opened. |

**Regime-gate caveat (recorded because it kills a tempting "filter"):** the
replica only enters a position when the PIT regime flag is ON, so a
"regime == 1" meta-filter is vacuous — every event in the population already
satisfies it. Filters must operate on continuous decision-time quantities.

---

## R6-A: frozen research contract

### 1. Population and labels

The 1,311 R5 events with R5 frozen-spec labels (+1/−1/0 semantics as
recorded; sign-resolved verticals included). No relabeling, no event
re-derivation, no barrier changes.

### 2. Feature contract (frozen list — no engineering)

Only these decision-time quantities, each with availability_timestamp =
the event's decision bar (R6-B verifies per feature):

```text
signed final weight (w_final)      |w_final|
cross-sectional rank (rk)          12−1 momentum value (sig)
regime flag (1 for all events)     vol60 (per-symbol, annualized)
vol_scale (capped scale)           avg_vol (market-level)
side (LONG/SHORT)
```

No interactions, no rolling transforms of features, no per-symbol feature
dummies beyond `side`. Any addition = a NEW preregistration.

### 3. Validation design (the R5-mandated constraint)

- **Random train/test splits are BANNED** on this population: overlapping
  label intervals share future price paths (R5: 663/1,311 events affected).
- All OOS evaluation uses the frozen R3 WF geometry (train 750 / test 250 /
  purge 10 / embargo 5, anchored — the `parameter_stability.grid` constants;
  NOTE: this contract prose originally miswrote "504 / purge 21", corrected
  2026-09-17 — see the correction record in the B1 status section).
- Purge/embargo operate on event timestamps **against label interval ends**
  (first-touch deadline), not bare bar indices — R6-B implements and
  hand-tests this.
- Training-fold samples are uniqueness-weighted (R5 module) inside every
  fitted model.

### 4. Baseline hierarchy (staged slots)

```text
B0  take-every-event population statistics   reference, no slot, not a model
B1  ONE deterministic filter                 slot R6-B1 (preregistered below)
B2  logistic regression                      slot R6-B2, gated on B1 design proven
B3+ anything more complex                    BANNED in R6 absent a NEW
                                             preregistration + demonstrated B2
                                             incremental OOS evidence
```

Explicitly banned ladder for R6: random forest / gradient boosting / neural
nets / ensembles / hyperparameter sweeps. If logistic regression fails to
add incremental value under this design, that is itself evidence, and the
branch stops there.

### 5. R6-B1 preregistration (declared BEFORE any conditional label rate)

**The ONE filter: skip events whose entry weight was vol-capped.**

```text
take event  iff  vol_scale < 1.0   (⟺ vol60 < VOL_SCALE_REFERENCE = 50%)
skip event  iff  vol_scale == 1.0  (vol-capped at the frozen reference)
```

Rationale (ex ante): the 50% reference is a frozen R4 specification
constant — the filter introduces no fitted threshold. Economic hypothesis:
momentum entries into already-high-volatility states (capped scale) are the
poor-quality subset.

**H1-B1:** the favorable-label rate among taken (uncapped) events exceeds
the rate among skipped (capped) events, OOS-relevantly — evaluated over the
full event population with WF-geometry OOS reporting (rates are computed
per WF window; the headline is the full-period difference).

**Evaluation (frozen):** rate difference + moving-block bootstrap CI over
the date-ordered signed-label sequence (block_length = 20, seed 42 — reusing
the R1 B3 engine for its second consumer). Overlap caveat recorded: block
bootstrap mitigates but does not eliminate label-interval dependence.

**Success:** rate difference > 0 with a 90% CI excluding 0 (predeclared,
one-sided rationale). **Failure:** CI includes 0 or the difference is
negative. **Either way B1 is a filter-quality result, not a strategy
verdict** — "take/skip" here characterizes event quality only.

### 6. The bar for the whole branch (frozen definition)

A meta-layer earns further research ONLY by demonstrating **incremental OOS
utility over take-every-event R4, after costs**. Never by accuracy, AUC,
class balance, or in-sample separation. The R5 label split (681/630) is an
instrument property and must never be quoted as "baseline accuracy".

For B2 (operational addendum to be frozen before B2 code, same pattern as
R3/R4): utility_delta = mean net P&L of taken OOS events − mean net P&L of
all OOS events (B0), significance preregistered at that time.

### 7. Branch rejection criteria

- (a) B1 shows no positive rate difference AND B2 shows no OOS incremental
  utility → the meta-labeling branch is **REJECTED on this data** (recorded;
  no model-ladder escalation, no feature-engineering follow-ups).
- (b) Any leakage/PIT defect → result discarded, defect fixed, re-run under
  the same preregistration.
- (c) WF windows cannot fit, or OOS events are insufficient →
  **INCONCLUSIVE**; the branch is parked with the R4 discipline (new data
  class required to reopen, not more attempts).

### 8. Trials, scope, guards

- R6-B1 and R6-B2 are separate preregistered slots. A new feature, filter,
  model family, or metric = a new preregistration.
- Research-only: take/skip is studied at the label level. No production
  path exists; R4 production and the R4-S evidence stream are untouched.
- No forecast language: every OOS number is a statement about this
  experiment on this dataset.

---

## R6-B1 status: COMPLETE — INCONCLUSIVE (filter class empty) (2026-09-17)

**Execution:** `scripts/run_r6_b1_baseline.py` — full pre-execution check
suite PASSED, then the preregistered evaluation.

**Pre-execution checks (all clean):**
- feature availability: 0 failures across all 1,311 events (every decision-
  time feature read at the decision bar, finite)
- weights identity: re-derived final weights equal the replica's weights
  EXACTLY for every event (0 failures) — the feature copy is the frozen
  pipeline, not a fork
- event↔round-trip correspondence: 1,311 events = 1,311 entry fills =
  1,311 round-trips → OK
- labels: 1,311 (R5 deterministic re-run), 0 excluded
- WF fit: 1,311 events ≥ 1,010-bar geometry (train 750 + purge 10 + test
  250) → OK. CORRECTION (2026-09-17): this record originally said
  "530-bar geometry", a prose error; the executed runner imported the real
  frozen constants and the authoritative artifact
  (`r6_b1_report.json` → `wf_fit.train_purge_test = 1010, ok = true`) was
  always correct. No result changes.

**Result — the preregistered filter is VACUOUS on this data:**

| | |
|---|---|
| taken (vol_scale < 1.0) | **1,311** |
| skipped (vol_scale == 1.0) | **0** |
| rate difference / CI / verdict | undefined → **INCONCLUSIVE** (missing evidence stays missing) |

**Why (structural, not a bug):** the replica only enters when the PIT regime
flag is ON, and the regime gate (avg_vol < expanding median) is precisely a
high-volatility suppressor. By the time an event exists, its vol60 is
essentially never above the 50% reference, so nothing ever gets vol-capped
at entry. The filter's skip class is empty because **R4's own regime gate
already performs the filter's intended job upstream** — an accidental
confirmation that the R4 architecture suppresses exactly the states the
filter targets, recorded here as an OBSERVED design property, not a
performance claim.

**Interpretation guards:**
- INCONCLUSIVE is not SUCCESS and not FAILURE; the B1 criterion was never
  exercisable on this population.
- The trial slot R6-B1 is consumed by this INCONCLUSIVE result.
- No replacement filter may be invented in response (that would be
  threshold-shopping); a different deterministic filter = a NEW
  preregistration with a declared rationale.
- The vacuousness is a population property of the frozen replica on this
  dataset — it does not generalize to other universes or data classes.

**B2 gate status:** the contract gates B2 (logistic regression) on "B1
design proven". The DESIGN proved out (checks, splits, CI machinery,
determinism — all exercised and tested); the FILTER is vacuous. B2 does
NOT run: the prerequisite is not "can the machinery execute" but "has B1
established a non-vacuous decision problem that justifies learning a
conditional relationship" — and the answer is no. Jumping to ML here would
ask it to discover a conditional edge the prerequisite experiment never
demonstrated exists. Meta-labeling is a secondary model conditional on an
existing primary signal; it cannot manufacture the primary edge.

**DISPOSITION: R6-B1 — COMPLETE / INCONCLUSIVE / PARKED (2026-09-17).**

Governing interpretation (frozen):

> The preregistered deterministic meta-filter was non-exercisable on the R4
> event population because the production R4 regime gate already excluded
> the targeted high-volatility states. B1 therefore provides no evidence
> for or against conditional event selection. The meta-labeling branch is
> parked rather than advanced to ML. Reopening requires either a materially
> different, preregistered filter rationale or a new data class.

Scope of the claim (supported vs not-established, frozen):

- **Supported by current evidence:** this particular filter has no
  discriminating power on this event population because it never activates.
- **NOT established:** "no decision-time feature can distinguish good from
  bad R4 events." That broader claim has not been tested and is not made.

No threshold-shopping: adjusting the cutoff (0.9, 0.8, 1.1, vol30, vol90, …)
until a contrast appears would be searching the same 1,311 events — exactly
the attractive-region failure R3 demonstrated. A new filter is researchable
only with a new rationale and a new trial slot declared before its result
is seen.

**Verification:** 15 new unit tests (hand-computed splits/rates, CI
determinism + degenerate classes, WF slices, verdict paths); 720/720
research suite; ruff + mypy clean.
