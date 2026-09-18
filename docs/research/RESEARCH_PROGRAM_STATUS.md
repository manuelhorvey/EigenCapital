# EigenCapital Research Program — Status (FROZEN)

**Date:** 2026-09-17
**HEAD at closure:** 0b297a9
**Status:** RESEARCH QUEUE CLOSED · PRODUCTION R4 UNCHANGED
**Governing reviews:** [RESEARCH_LITERATURE_AUDIT_REVIEW.md](RESEARCH_LITERATURE_AUDIT_REVIEW.md) · per-stage ledgers below

---

## Final queue state

| Stage | Ledger | Verdict (exact, do not soften) |
|---|---|---|
| R0 Infrastructure | [R0_INFRASTRUCTURE_VERIFICATION.md](R0_INFRASTRUCTURE_VERIFICATION.md) | **COMPLETE** |
| R1 Monte Carlo | [R1_MONTE_CARLO.md](R1_MONTE_CARLO.md) | **COMPLETE / FROZEN** (A ✅ B1 ✅ B2 ✅ B3 ✅ B4 ✅; dependence effect: IID understates drawdown/streak/recovery tails vs block resampling) |
| R2 Factor Lab | [R2_FACTOR_LAB.md](R2_FACTOR_LAB.md) | **COMPLETE / FROZEN** — lab validated; first preregistered factor **REJECTED** (momentum_12_1 × r4_local_v1 × h=21: mean rank IC −0.0440, Holm p 0.4398, stress-cost spread negative) |
| R3 Parameter Stability | [R3_PARAMETER_STABILITY.md](R3_PARAMETER_STABILITY.md) | **COMPLETE / H1 FALSIFIED** — frozen config **OUTSIDE_STABLE_REGION** (92% of 1,500 points fragile; PBO 1.000 across 16/16 partitions with non-independence caveat; DSR 0.0019 n.s.); observed axis associations quarantined — acting on them requires a NEW preregistration |
| R4 Mean Reversion | [R4_MEAN_REVERSION.md](R4_MEAN_REVERSION.md) | **INCONCLUSIVE → CLOSED / PARKED** — B1: 2 pairs, 1 trade; B2: 8-pair preregistered expansion, 5 trades < 20 → parking rule fired; gate starvation structural on daily bars; reopening requires a new data class |
| R5 Triple Barrier | [R5_TRIPLE_BARRIER.md](R5_TRIPLE_BARRIER.md) | **COMPLETE / FROZEN** — instrument validated (1,311 events = TS-R4-D1-0001, 0 exclusions, byte-identical determinism, PIT proven by perturbation); overlap characterized (492 pairs, 663 events, mean uniqueness 0.837); NOT evidence of predictive power |
| R6 Meta-Labeling | [R6_META_LABELING.md](R6_META_LABELING.md) | **INCONCLUSIVE → CLOSED / PARKED** — B1 design exercised end-to-end; preregistered filter **vacuous** (skip class empty: R4's upstream regime gate had already excluded the targeted states); B2 correctly not run; supported claim is filter-specific, NOT "no feature can work" |
| R7 Order-Flow Entropy | — | **BLOCKED — DATA** (requires trade/order-flow data that does not exist locally; OHLC proxies banned) |
| R8 Strategy Portfolio | — | **DEFERRED** (requires ≥1 additional validated strategy family; none exists) |

**Trial slots consumed:** R2-B1 (1) · R3-B1 (1) · R4-B1 (1) · R4-B2 (1) · R5-B1 (1) · R6-B1 (1). Every slot's verdict recorded above; no slot re-opened; no post-hoc filter/threshold shopping.

---

## Result vocabulary (project-wide, not interchangeable)

```text
FALSIFIED     evidence contradicts the preregistered hypothesis
              under the declared experiment            → R3 (H1), R2 (factor)
INCONCLUSIVE  the experiment did not generate sufficient
              evidence to decide the hypothesis        → R4-B1, R6-B1
PARKED        further work under the current data/assumption class is not
              justified; reopening requires a MATERIAL change
              (new data class or new preregistered rationale) → R4, R6
```

INCONCLUSIVE is never read as a pass. PARKED is never read as falsified, and
vice versa. No VALIDATED verdict exists in EigenCapital research; the best
available research outcome is CANDIDATE within research only.

---

## The process that produced this record

```text
hypothesis → preregistration (ledger, BEFORE code/data access)
          → frozen implementation + tests
          → ONE trial slot, deterministic execution
          → falsification / evidence gate (missing evidence → INCONCLUSIVE, never PASS)
          → recorded result, exact vocabulary
          → FREEZE / PARK / REJECT — never retroactive search expansion
```

---

## Production boundary (permanent)

**Nothing in R0–R6 constitutes permission to alter frozen R4.** The program
generated diagnostics, rejections, falsifications, instrument
characterizations, and data-dependency findings — not a new production
specification. Any future R4 modification is a NEW strategy candidate under
the frozen stage-boundary process, never an "improvement." R4-S forward/soak
evidence remains the only production decision path.

---

## Reopening rules (frozen)

1. New research starts with a NEW preregistration and fresh trial accounting
   — never by quietly extending R2–R6 (that would contaminate their records).
2. Parked stages reopen only via a materially different preregistered
   rationale or a new data class (intraday / order-flow for R4-MR and R7).
3. R8 requires at least one additional validated strategy family, which does
   not exist.
4. "The queue is closed" means the currently justified program is exhausted
   without manufacturing evidence — not that research is finished forever.

---

## Evidence artifact index

**Machine-readable program record:** `reports/research_program/program_status.json`
— canonical stage verdicts, trial-slot ledger, production-boundary flags, and
reopening rules in structured form. In any disagreement between the JSON and
this document, this document governs and the JSON must be corrected to match.

| Stage | Artifacts |
|---|---|
| R1 | `reports/r1_monte_carlo/` — trade stream TS-R4-D1-0001, evidence report (JSON/MD) |
| R2 | `reports/r2_factor_lab/` — first-factor experiment report |
| R3 | `reports/r3_parameter_stability/` — 1,500-point grid surface + verdicts |
| R4 | `reports/r4_mean_reversion/` — B1 (2-pair) + B2 (8-pair) reports, per-pair trade CSVs |
| R5 | `reports/r5_triple_barrier/` — label run JSON/CSV/MD (per-event audit trail) |
| R6 | `reports/r6_meta_labeling/` — B1 report with pre-execution checks |

Verification at closure: **720/720 research tests · ruff clean · mypy clean
(86 source files)**. Research modules live under
`src/eigencapital/research/{monte_carlo,factor_lab,parameter_stability,mean_reversion,labeling,meta_labeling}/`
with runners in `scripts/run_r{1..6}_*.py` and the shared pipeline exporter
`scripts/export_r4_trade_stream.py`.

---

## Post-closure addendum (2026-09-17, after queue closure)

[DATA_REQUIREMENTS.md](DATA_REQUIREMENTS.md) has been drafted as a CONTRACT
document defining what a "material data upgrade" means for the two
data-blocked stages (R7 order-flow; R4-MR intraday). It is not a
preregistration, opens no trial slots, and authorizes no experiment — it
specifies the data contract, quality gates, and reopening flow that any
future reopening must satisfy first. Nothing in this status document is
reinterpreted by it.
