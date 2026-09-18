# R0 — Research Infrastructure Verification

**Date:** 2026-09-17
**Branch:** main
**HEAD:** 0b297a9
**Governing documents:**
[RESEARCH_LITERATURE_AUDIT_REVIEW.md](RESEARCH_LITERATURE_AUDIT_REVIEW.md) (frozen R0–R8 queue, §14 stage-boundary table, §15 R0 handoff) and
[RESEARCH_LITERATURE_INTEGRATION_AUDIT.md](RESEARCH_LITERATURE_INTEGRATION_AUDIT.md) (§21 module map)

**R0 mandate (from review §9/§15):** Inspect the *existing* EigenCapital research machinery against the frozen R0–R8 requirements. Produce a very small gap list classified **PASS / PATCH / BLOCKED / DEFERRED**. Only patch demonstrable gaps. If no material defects, proceed directly to R1 — Monte Carlo.

**Method:** Code-level inspection of each R0 checklist item against the actual modules. No new research code written in R0.

---

## Verdict

> **R0: PASS with minor patches.** All nine checklist items exist and are structurally adequate. No material defects. One gap is material for the frozen roadmap: **no persistent historical trade-stream repository exists** — `BacktestResults` keeps trade evidence as in-memory `fill_events` dicts and production trade records live only in qualification datasets. This is the single input dependency of R1 Monte Carlo, so it is classified **PATCH (pre-R1)**, small and additive. R7 order-flow entropy is confirmed **BLOCKED — DATA DEPENDENCY** (no tick/trade-direction data on disk; `data/tick_micro_m5/` is empty).

**Proceed to R1 — Monte Carlo after the trade-stream patch.**

---

## 1. Gap List

| # | Item (R0 checklist) | Status | Evidence | Notes |
|---|---------------------|--------|----------|-------|
| 1 | Experiment registry | **PASS** | `research/experiments/registry.py` | Full lifecycle `PRE_REGISTERED → RUNNING → COMPLETED → CANDIDATE \| REJECTED`; parameter freezing makes frozen experiments immutable; `trial_metadata` embedded |
| 2 | Hypothesis registry | **PASS** | `research/hypotheses/hypothesis.py` + 30+ hypothesis files in `research/hypotheses/` | Mandatory `falsification_criteria`; status lifecycle DRAFT→REGISTERED→TESTED→REJECTED/SUPPORTED; extensive actual usage |
| 3 | Trial counting | **PASS** | `core/models/trial_metadata.py` | Trial families with 1-based `trial_index`, `trials_in_family`, `selection_method`, `parameter_search_space`; documented purpose: deflated-Sharpe-style selection-bias quantification |
| 4 | Feature availability | **PASS** | `features/feature.py`, `features/feature_set.py`, `features/pipeline.py` | Enforced invariant `availability_timestamp <= decision_timestamp` raises on violation; all feature families stamp availability; pipeline emits it |
| 5 | Cost model | **PASS** | `core/costs` (canonical), re-exported via `research/costs/model.py` with `ZERO/MODERATE/STRESS` presets | Mandatory in `BacktestEngine` ("Cost accounting (mandatory cost model)"); stress preset exists for §23 cost-stress gates |
| 6 | WFA (walk-forward) | **PASS** | `analytics/validation/walk_forward.py` | `purged_walk_forward` with train/test/purge/embargo bars; used by campaigns (`research/campaigns/r5_executor.py`: `WF_TRAIN=504, WF_TEST=126, WF_PURGE=5, WF_EMBARGO=5`) |
| 7 | Purging / embargo | **PASS** | Same module | Explicit purge-vs-embargo semantics (purge before test window for label-horizon overlap; embargo after for serial correlation); returns never computed across segment boundaries |
| 8 | Multiple-testing | **PASS** | `analytics/validation/multiple_testing.py` (Bonferroni, Holm, Benjamini-Hochberg/FDR) + `analytics/validation/evidence_gate.py` | Campaigns apply family-wise correction to permutation p-values; freeze files pin `multiple_testing_config_hash` |
| 9 | Provenance | **PASS** | `research/provenance/` (hashing, manifest) | `ResearchManifest` records git commit, package version, dataset id/version/hash, strategy/config/artifact hashes, cost model id/version, seed, parent experiment lineage |
| 10 | Historical trade stream | **PATCH (pre-R1)** | `backtest/engine.py` (`BacktestResults`), `production_qual/` trade records | Trade P&L sequence exists transiently (in-memory `fill_events`, qualification datasets) but **no persistent, retrieval-friendly trade-stream repository**. This is R1 Monte Carlo's sole input. Small additive module; no production impact |
| 11 | OHLC/price history | **PASS (data exists)** | `data/raw/`, `data/normalized/`, `data/intraday_m1/m15/m30/h1/` | Sufficient for R2 Factor Lab, R3 Parameter Stability, R4-stage MR/Stat-Arb (FX pairs), R5 Triple Barrier |
| 12 | Tick / order-flow data | **BLOCKED** | `data/tick_micro_m5/` empty; no trade-direction/bid-ask/depth anywhere | R7 order-flow entropy requires trade sequence + direction (+ possibly bid/ask/depth). Review §7 already marked BLOCKED — DATA DEPENDENCY; confirmed against disk. **Do NOT build OHLC→entropy proxies** |
| 13 | Validated strategy families beyond R4 | **DEFERRED** | Strategy layer: R4 frozen + production; MR/stat-arb = hypotheses only (`research/hypotheses/statistical_arbitrage/`, `mean_reversion/`) | R8 Strategy Portfolio requires ≥1 additional validated family (review Tier 3). No action until R4-stage MR/Stat-Arb survives validation |

**Classification summary: 9 PASS · 1 PATCH (pre-R1, small) · 1 BLOCKED (data) · 1 DEFERRED (intentionally later) · 1 PASS-with-data (price history).**

## 2. What Was Explicitly NOT Done (Scope Discipline)

Per the frozen stage-boundary table (review §14) and §25 preference order of the audit:

- **No new research modules created.** The only identified code patch (trade-stream repository) is deferred to the start of R1, where it belongs as that stage's input adapter.
- **No purged-CV/embargo/validation "strengthening."** The original audit's Phase 1 idea was rejected in review §1 — this machinery exists and passed inspection; rebuilding it would polish tested infrastructure instead of generating evidence.
- **No R4 modification, no risk-engine or execution changes.** Everything inspected is research-side.
- **No entropy proxies built from OHLC.** Data dependency documented instead.

## 3. Notes Supporting the Two Non-PASS Items

### PATCH — historical trade stream (the R1 input)

What exists already:

- `BacktestResults.fill_events` — fill-level events (price, side, quantity) per backtest run
- `production_qual/live_qualification.py` + `production_qual/evidence_orchestrator.py` — closed-trade records with entry/exit details, MAE/MFE, append-only evidence

What R1 needs: a deterministic, provenance-stamped sequence of closed-trade P&Ls (per-trade returns with timestamps) loadable from a persisted artifact, so Monte Carlo reshuffling/bootstrap/block-bootstrap consume *the same stream* the historical statistics were computed from — no re-derivation, no ambiguity about which trade set produced which distribution.

Classification as PATCH rather than new-stage work: it is an **input adapter** for R1, additive, research-only, and small.

### BLOCKED — order-flow data

Confirmed empty `data/tick_micro_m5/`; no trade-direction, bid/ask, depth, or order-book fields anywhere in `data/` or the data contracts. Review §7's restriction stands: entropy is **BLOCKED — DATA DEPENDENCY** until a data contract exists. Any OHLC-derived "entropy" would be exactly the synthetic sophistication the review forbids.

---

## 4. R0 Exit Criteria

| Criterion | Result |
|-----------|--------|
| All nine frozen-checklist items verified against code (not docs) | ✅ |
| Only demonstrable gaps actioned | ✅ (one PATCH identified, deferred to R1 as input adapter) |
| No architecture redesign, no R4 modification | ✅ |
| Gap list produced with PASS/PATCH/BLOCKED/DEFERRED | ✅ |
| Material defects found | ❌ none |

**Decision: R0 COMPLETE. Next stage: R1 — Monte Carlo Diagnostics** (starting with the trade-stream input adapter), per review §9 R1 and §10 Tier 1.

---

## Source Map ( inspected modules )

| Module | Role in R0 verification |
|--------|------------------------|
| `src/eigencapital/research/experiments/registry.py` | Experiment lifecycle + immutability + trial metadata |
| `src/eigencapital/research/hypotheses/hypothesis.py` | Pre-registration + falsification criteria |
| `src/eigencapital/core/models/trial_metadata.py` | Trial families / multiple-testing provenance |
| `src/eigencapital/features/feature.py` / `feature_set.py` / `pipeline.py` | Availability-timestamp invariant enforcement |
| `src/eigencapital/core/costs.py` (+ `research/costs/model.py`) | Cost model presets incl. STRESS |
| `src/eigencapital/analytics/validation/walk_forward.py` | Purged + embargoed WFA |
| `src/eigencapital/analytics/validation/multiple_testing.py` | Bonferroni / Holm / BH-FDR |
| `src/eigencapital/analytics/validation/evidence_gate.py` | Combined evidence gate |
| `src/eigencapital/analytics/validation/factor_evaluation.py` | IC / quantiles / turnover (R2 foundation — already exists) |
| `src/eigencapital/analytics/validation/block_bootstrap.py` | Block bootstrap (R1 building block — already exists) |
| `src/eigencapital/research/provenance/manifest.py` / `hashing.py` | Experiment identity manifests |
| `src/eigencapital/backtest/engine.py` | `BacktestResults` — where trade evidence currently lives |
| `data/` tree | Price data present; tick/order-flow data absent |
