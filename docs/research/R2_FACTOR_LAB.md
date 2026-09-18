# R2 — Alpha Factor Laboratory

**Date:** 2026-09-17
**Branch:** main
**HEAD:** 0b297a9
**Governing documents:** [RESEARCH_LITERATURE_AUDIT_REVIEW.md](RESEARCH_LITERATURE_AUDIT_REVIEW.md) §9 (R2 = Factor Lab: "discover/test candidate explanatory features") · [R0_INFRASTRUCTURE_VERIFICATION.md](R0_INFRASTRUCTURE_VERIFICATION.md) (factor_evaluation.py PASS) · [R1_MONTE_CARLO.md](R1_MONTE_CARLO.md) (R1 COMPLETE/FROZEN)

---

## Phase R2-A — Factor-Lab Contract Verification (this document)

Per the frozen R1→R2 handoff: **R2 begins with an infrastructure/research-contract inspection, not with inventing factors.** Same pattern as R1-A: verify the existing machinery, freeze the research contract, *then* one narrowly scoped preregistered factor evaluation.

**Scope guard (frozen review §14):** R2 is research-only. It never modifies R4, the risk engine, or execution. The factor lab answers "is this feature informative?" — never "is R4 valid?"

### 1. Existing infrastructure verification (code-level, not doc-level)

| Component | Status | Evidence |
|-----------|--------|----------|
| IC / Rank IC | **PASS — reuse** | `analytics/validation/factor_evaluation.py::information_coefficient` — per-period Spearman IC, IC IR, t-stat, % positive, min_names guard for narrow cross-sections; 24 existing tests in `tests/unit/analytics/test_factor_evaluation.py` (suite: 157 passed) |
| Quantile construction | **PASS — reuse** | `quantile_analysis` + `quantile_spread_series` — even buckets, ties by rank position, direction + monotonicity verdicts, per-period spread series |
| Turnover | **PASS — reuse** | `factor_turnover` — top-set membership turnover + rank autocorrelation over common names, configurable `top_fraction` |
| Cost model | **PASS — reuse** | `core/costs.py` `CostModel` (versioned, explicit; ZERO/MODERATE/STRESS presets) |
| Multiple-testing correction | **PASS — reuse** | `analytics/validation/multiple_testing.py` — Bonferroni, Holm, Benjamini-Hochberg |
| Evidence gate | **PASS — reuse** | `analytics/validation/evidence_gate.py` — falsification-first; **missing evidence → INCONCLUSIVE, never PASS** |
| Trial-group accounting | **PASS — reuse** | `core/models/trial_metadata.py` `TrialMetadata` — trial families, 1-based index, selection_method, search space |
| PIT availability stamps | **PASS — reuse** | `features/feature.py` — enforced invariant `availability_timestamp <= decision_timestamp`; `features/feature_set.py` validates the whole set |
| Feature registry | **PASS — reuse** | `features/registry.py` — versioned registration, duplicate prevention |
| **Factor observation assembly** | **GAP — R2-B1** | Nothing joins signal panels + forward returns + PIT stamps + universe into the `(factor, period, name, signal, fwd_return)` observation record the lab consumes |
| **Forward-return alignment helper** | **GAP — R2-B1** | The panels the IC functions expect must be constructed with an explicit, frozen horizon convention; no canonical helper exists |
| **Universe + missing-data policy** | **GAP — R2-B1** | No canonical eligibility/missing-data contract for factor panels (per-symbol adapter pattern from R1 applies) |
| **Cost-adjusted spread view** | **GAP — R2-B1** | Spreads are gross; the lab needs the frozen cost haircut convention to express economic credibility |

**Verification run:** contract imports OK; `tests/unit/analytics/` 157 passed.

### 2. Frozen factor-lab research contract (recorded BEFORE R2-B1 code)

1. **Factor observation.** One observation = `(factor_id, period_date, symbol, signal_value, forward_return, availability_ts, decision_ts)`. A panel = all observations for one period. The lab consumes panels; it never constructs signals itself.
2. **Point-in-time availability.** Every signal value must carry `availability_timestamp <= decision_timestamp` (enforced by the existing `Feature` invariant). No exception path.
3. **Forward-return alignment.** Frozen convention: forward return = close-to-close return from the decision bar's close over `horizon` trading days, computed only from bars with `bar_end <= decision_ts + horizon`. Overlapping horizons are permitted but must be declared in the experiment's trial metadata (they inflate the effective sample; the declared count is what multiple-testing uses).
4. **IC definition.** Spearman rank IC per period (existing function), `min_names` floors narrow periods (skipped, not diluted). Rank IC is the primary IC; no Pearson IC without preregistration.
5. **Quantile construction.** Even buckets via existing `_assign_quantiles`; Q1 = highest signals; spread = Q1 minus bottom; per-period spread series for decay views.
6. **Turnover.** Existing `factor_turnover` with preregistered `top_fraction`; turnover is reported, not optimized.
7. **Costs.** Factor credibility is judged on the cost-adjusted top-minus-bottom spread: gross spread minus (one-way cost × 2 × turnover per period). Cost model id/version recorded. The STRESS preset is the falsification-stress reference.
8. **Universe handling.** The universe is a preregistered, versioned symbol list (R2 first experiment: the 8 locally available R4-eligible instruments). Universe changes create a new universe version — they never silently alter an existing experiment's panel.
9. **Missing-data policy.** A symbol missing a signal or a computable forward return for a period is **excluded from that period's panel** (and the exclusion count is reported). No imputation, no fill-forward of signals across rebalances.
10. **Trial-group accounting.** Every factor evaluation registers a `TrialMetadata` family (e.g. `factor_lab/<factor_id>/<horizon>`). **The factor library is a search: each candidate factor/horizon consumed one trial slot at registration time**, before results are seen. No post-hoc family resizing.
11. **Multiple-testing treatment.** Per-metric p-values (IC t-stat, spread sign test) are corrected **across the whole registered trial family** via the existing correction module; the correction method is preregistered (Holm).
12. **Falsification criterion (preregistered).** A factor is REJECTED for a given family if: mean IC ≤ 0 after Holm correction across the family, OR the cost-adjusted top-minus-bottom spread ≤ 0 at the preregistered cost model, OR the PIT invariant is violated anywhere in its panel. Missing data beyond a preregistered exclusion budget → INCONCLUSIVE (never PASS), consistent with the evidence gate's no-silent-pass rule.

### 3. Preregistered first experiment (R2-B1, narrowly scoped)

> **H0:** The preregistered momentum factor (12-1 month, the R4 signal's own construction, computed point-in-time) has mean rank IC ≤ 0 across the frozen universe at the preregistered horizon.
>
> **Purpose:** validate the LAB on a factor whose construction is already frozen elsewhere — not to discover a new edge. If the lab cannot reproduce a directional IC for the platform's own canonical signal under the frozen contract, the lab (not the factor) is the finding.
>
> **Scope:** ONE factor, ONE horizon, ONE universe version, ONE trial slot. No factor sweep. No "calculate 100 factors and rank by IC."

### 4. Explicitly out of scope for R2-B1

- Factor sweeps, factor-library generation, ML/meta-labeling (R5/R6 stages)
- Any change to `factor_evaluation.py` (it is verified infrastructure; R2-B1 *consumes* it)
- Universe expansion beyond local data (documented 8-of-17 limitation carries over from R1)
- Production integration of any kind

---

## Phase R2-B1 — Contract-honoring Factor Evaluation (COMPLETE 2026-09-17)

Deliberately boring: assemble → validate → measure → report → freeze.

### What was built

| File | Role |
|------|------|
| `research/factor_lab/observations.py` | `build_factor_panels` — frozen forward-return alignment (window starts AFTER the decision bar; factor(t)→return(t) structurally impossible), PIT enforcement with raise, per-period exclusion counting (no imputation), explicit overlap acknowledgment |
| `research/factor_lab/evaluation.py` | `evaluate_factor` — IC/quantiles/turnover via the verified infrastructure; cost-adjusted spread (gross − 2×one-way×turnover); preregistered Holm correction; verdicts REJECTED / INCONCLUSIVE / CANDIDATE (**never VALIDATED** from a single-factor panel study); degenerate zero-variance IC handled honestly (constant positive IC → p=0, not p=1) |
| `tests/unit/research/factor_lab/test_factor_lab.py` | 19 unit tests (anti-leakage alignment proven exactly, PIT raise, exclusions, verdict paths, Holm wiring, determinism) |
| `scripts/run_r2_first_factor.py` | The preregistered experiment runner |
| `reports/r2_factor_lab/r2_b1_first_factor.json` | Evidence artifact |

### Preregistered experiment result (as frozen in §3)

| Item | Value |
|------|-------|
| Factor | momentum_12_1 (R4's own construction, PIT-computed) |
| Universe / horizon | r4_local_v1 (8 symbols) / 21 bars, monthly decisions |
| Panels | 86 periods, 688 observations, exclusions 1.15% (within budget) |
| Mean rank IC | **−0.0440** (t=−0.77, n=86, 41% of periods positive) |
| Holm p | 0.4398 — H0 (IC ≤ 0) **not rejected** |
| Gross / cost-adjusted spread | −0.000661 / −0.001661 (STRESS haircut; turnover 1.000 at top-third) |
| **Verdict** | **REJECTED** (both falsification arms) |

### Interpretation (frozen boundaries)

- The preregistered H0 was not rejected: at a 21-bar horizon on the r4_local_v1 universe, the canonical 12-1 momentum construction shows no positive cross-sectional rank information — and the cost-adjusted spread is negative at stress costs regardless.
- **This is a laboratory validation, not a strategy verdict.** The lab faithfully assembled point-in-time panels (exclusions 1.15%, PIT clean, alignment anti-leakage proven by test) and produced a deterministic, Holm-corrected, no-silent-pass disposition. The machinery works; the factor — at THIS horizon, THIS universe, THESE costs — does not clear the preregistered bar.
- Consistent context (not an excuse): R4 production does not trade this factor as a monthly-horizon cross-sectional book — it applies regime gating, vol scaling, weekly rebalance and portfolio construction. Nothing here modifies or re-evaluates frozen R4 (stage-boundary table, review §14).
- The REJECTED verdict consumes exactly the preregistered trial slot (`factor_lab/momentum_12_1/h21`, family size 1). No sweep was run; no additional horizons/universes were searched; any such expansion is a NEW preregistration with new trial slots.

### Verification results

| Check | Result |
|-------|--------|
| Factor-lab unit tests | **19 passed** |
| Full research suite | **633 passed** — no regressions |
| `ruff check` + `ruff format` | Clean |
| `mypy` | Success, no issues |

### R2-B1: COMPLETE / FROZEN

Next (subject to the same preregistration discipline): additional factors/horizons ONLY as new preregistered experiments consuming new trial slots — the lab is proven, so expansion is now a matter of research prioritization rather than infrastructure.
