# R4 — Mean Reversion / Statistical Arbitrage Research Family

**Date opened:** 2026-09-17
**Branch:** main · **HEAD:** 0b297a9 (uncommitted research series)
**Governing documents:** RESEARCH_LITERATURE_AUDIT_REVIEW.md §6/R4 · R0_INFRASTRUCTURE_VERIFICATION.md · the frozen queue (R0 ✅ → R1 ✅ → R2 ✅ → R3 ✅ → **R4 active**)

**Boundary (absolute, from the audit):** *"Do NOT alter R4 production strategy to become a mean-reversion strategy."* This ledger covers a **separate research family** (`research/mean_reversion/`). Nothing here touches the frozen R4 production strategy, its parameters, or its R4-S forward/soak evidence path.

**Naming disambiguation:** "R4 production strategy" (the frozen momentum spec) vs "stage R4" (this research phase) collide. In this document, **R4-MR** refers to this mean-reversion/stat-arb research stage; the production strategy is always called **frozen R4** or **production R4**.

---

## Stage R4-A: infrastructure verification (recorded before code)

| Component | Verdict | Evidence |
|---|---|---|
| Preregistered data | **PASS** | `data/mt5/{AUDUSDm,NZDUSDm,EURUSDm,GBPUSDm}_D1.csv` all exist; identical coverage 2020-01-02 → 2026-08-24, 2,076 bars each (verified head/tail/line-count). Daily bars only — the contract's `min_bars` threshold is set with that in mind. |
| Stationarity / cointegration machinery | **PASS — reuse `statsmodels`** | `statsmodels 0.14.6` installed: `adfuller`, `coint` (Engle-Granger) verified importable + smoke-tested (ADF on a synthetic random walk: stat −2.118, p 0.237 — correctly non-rejecting). **Deliberate decision: no in-house ADF reimplementation.** |
| Existing "pairs" code | **NOT REUSED — scope mismatch + methodological deficit** | `research/alpha/full_executor.py::compute_pairs_cointegration` (HYP-SA-001) is a **returns-spread z-score heuristic**: no ADF, no hedge ratio (implicit β=1 on returns), no cointegration gate, no half-life, cost handling absent (hard-coded turnover guess). Banned-proxy risk exactly as the audit warned. R4-MR builds a proper pipeline; that executor stays untouched. |
| Hedge-ratio estimation | **PASS — reuse `statsmodels` OLS** | Plain OLS of log-price on the pair's log-price; `numpy`/`pandas`/statsmodels all present. Rolling-window form chosen (see contract) to bound hedge-ratio drift rather than a single full-sample fit. |
| Half-life | **GAP → R4-MR scope** | No implementation anywhere in `src/`. Small pure function: AR(1) fit on the spread, φ → `hl = −ln(2)/ln(1+φ)`. |
| Correlation model (for pair diagnostics) | **PASS — reuse** | `shadow/portfolio/correlation.py` exists (no-lookahead truncation, multi-window). Used for diagnostics only; the pair pipeline itself uses its own PIT windows. |
| Governance | **PASS — reuse** | Hypothesis + experiment registries (`research/hypotheses/hypothesis.py`, `research/experiments/registry.py`) verified importable; Holm via `analytics/validation/multiple_testing.py`; cost convention 15 bps one-way as in R1/R3. |

**Conclusion:** the only genuinely new code for R4-B1 is the **pair pipeline itself** (rolling ADF → hedge ratio → spread → half-life → thresholds → cost → WF → OOS) plus explicit diagnostics. No statistical machinery is forked or reimplemented.

---

## Frozen R4-MR research contract (recorded before code)

**Pair pipeline (every candidate, in this order, with hard gates):**

```
candidate pair (preregistered universe only)
    ↓
economic-relationship statement (recorded, per pair)
    ↓
point-in-time ADF on LOG PRICES (gate 1: p < 0.05; levels, not returns)
    ↓
Engle-Granger cointegration (gate 2: p < 0.05), PIT window
    ↓
hedge ratio β (OLS, PIT window; ONLY IF gate 2 passes)
    ↓
spread = log(P_A) − β·log(P_B)
    ↓
half-life (AR(1) on spread; gate 3: 5 ≤ HL ≤ 60 trading days)
    ↓
entry |z| ≥ 2.0, exit |z| ≤ 0.5 (PIT rolling window; frozen, no search)
    │     (gate 4: ≥ 20 round-trips over the sample, else INCONCLUSIVE)
    ↓
cost model (15 bps one-way per leg, R1/R3 convention)
    ↓
purged walk-forward (reuse analytics/validation/walk_forward.py)
    ↓
regime diagnostics (shadow correlation model, multi-window)
    ↓
OOS reporting
```

**Frozen items (decided now, before any code runs):**

1. **Universe (preregistered, exactly two pairs):** `AUDUSDm/NZDUSDm` (commodity-bloc correlation; both vs USD) and `EURUSDm/GBPUSDm` (European bloc vs USD). Expansion requires a new preregistration.
2. **Price basis:** log prices for estimation (ADF, cointegration, hedge ratio, spread); thresholds applied to the spread's z-score.
3. **PIT convention:** every estimation window ends strictly BEFORE the decision bar (no exception path — mirrors R2's PIT raise).
4. **Rolling estimation:** re-estimate β, ADF, cointegration on a rolling 250-bar window, step 21 bars (monthly). Gates 1–2 evaluated per estimation date; periods failing the gates produce **no signal** (flat), never stale re-use.
5. **Thresholds frozen, no search:** entry |z| ≥ 2.0, exit |z| ≤ 0.5, z-window 60 bars, position sized ±1 unit spread notional. Any threshold exploration = new preregistration, new trial family.
6. **Half-life gate:** 5 ≤ HL ≤ 60 trading days, estimated PIT per window; HL outside the band at a decision date → no new entries that date.
7. **Sample gate:** ≥ 20 round-trips per pair over the full sample, else the pair's verdict is **INCONCLUSIVE** (missing evidence → never PASS).
8. **Costs:** 15 bps one-way per leg (10 config + 5 slippage), charged on every entry and exit, both legs.
9. **Walk-forward:** reuse `purged_walk_forward` (anchored, train=750, test=250, purge=10, embargo=5 — same geometry as R3 for comparability); windows that cannot fit reported with reason.
10. **Trial accounting:** this preregistration consumes **one trial slot for the two-pair family** (the family is the unit of evidence, not each pair). Family-level Holm is not needed for a single family; per-pair p-values are reported descriptively, never as a selection device.
11. **Falsification criteria (the whole family, all must hold for CANDIDATE):**
    - **F-A (statistical):** OOS mean spread return per trade > 0 across the family's pooled OOS trades, with sign-flip permutation p < 0.05 (reuse `analytics/validation` sign-flip machinery).
    - **F-B (economic):** pooled OOS total P&L remains positive AFTER full 15 bps/leg costs.
    - **F-C (portfolio rationale):** pairwise correlation of the pair strategy's daily returns with the frozen-R4 replica's daily returns (same window/data) < 0.7 — a stat-arb family whose returns merely clone momentum adds nothing.
    - Failure of any arm → family verdict **REJECTED**. Missing evidence (gates, insufficient trades) → **INCONCLUSIVE**, never PASS. **No VALIDATED verdict exists** (R2 convention).
12. **Promotion question (frozen):** NOT "can this match R4?" — **"Does the family demonstrate statistically and economically credible OOS behavior after costs, and provide incremental portfolio utility (F-C) beyond the existing momentum family?"** A lower-standalone-return strategy with different drawdown timing can still be valuable; matching R4 is neither required nor sufficient.
13. **Banned:** threshold sweeps (entry/exit/z-window/HL band), universe expansion without new preregistration, full-sample β or full-sample ADF used for trading decisions, return-based spreads as a substitute for the price-spread pipeline (the HYP-SA-001 pattern), silencing gate failures, any modification of frozen R4 production, and using stage-R4 outcomes to justify R4-production parameter surgery (R3's falsified H1 is closed).
14. **Artifacts:** `reports/r4_mean_reversion/r4_b1_pairs_report.{json,md}` + per-pair diagnostics CSVs; runner `scripts/run_r4_b1_pairs.py`.
15. **Status:** R4-A COMPLETE. R4-B1 **NOT STARTED**.

---

## Pre-execution addendum (recorded BEFORE the first real pair run)

- **OOS operationalization (F-A/F-B):** a trade is OOS when its EXIT bar
  index in the pair's common calendar is ≥ `WF_TRAIN_BARS + WF_PURGE_BARS +
  WF_EMBARGO_BARS` (= 765, the frozen R3 walk-forward geometry). All pipeline
  decisions are already PIT w.r.t. their estimation windows; this split makes
  the "OOS" language of item 11 concrete and non-negotiable after the fact.
- **F-A statistic:** per-trade GROSS spread P&L (pre-cost) of pooled OOS
  trades, sign-flip permutation via `analytics/validation/bootstrap.
  permutation_test` (n=1000, seed=42). Costs enter F-B, not F-A.
- **F-B statistic:** pooled OOS NET total P&L (4 × 15 bps per round trip
  already deducted by the pipeline) > 0.
- **F-C statistic:** Pearson correlation over the common daily index between
  (a) the pooled family daily return series (mean of the two pairs' daily
  series per date) and (b) the frozen-R4 replica daily path from the R1
  exporter (`compute_r4_signal` + `daily_portfolio_path`, 15 bps) over its
  8-symbol eligible universe. Gate: correlation < 0.7.
- **Family verdict:** CANDIDATE requires ≥ 1 pair to pass the sample gate
  (≥ 20 round-trips) AND F-A AND F-B AND F-C. Any failed arm → REJECTED;
  missing evidence (no OOS trades, sample gate failed everywhere) →
  INCONCLUSIVE. Per-pair results are diagnostics, never a selection device.
- **Reported diagnostics per pair:** gate coverage (estimation dates, active
  regimes, failure counts by gate), trade count, hit rate, mean/median net
  P&L per trade, WF aggregate (frozen R3 geometry, windows-that-cannot-fit
  reported with reason), cancelled entries, force-closed positions.
- **Execution:** deterministic (no RNG except the seeded permutation test).
  Runner `scripts/run_r4_b1_pairs.py`; artifacts
  `reports/r4_mean_reversion/r4_b1_pairs_report.{json,md}` + per-pair
  diagnostics CSVs.

## R4-B1 status: COMPLETE — INCONCLUSIVE (2026-09-17)

**Execution:** both preregistered pairs ran through the frozen pipeline
deterministically (no RNG except the seeded permutation test, which was not
reached — see below). Runner: `scripts/run_r4_b1_pairs.py`; artifacts in
`reports/r4_mean_reversion/` (JSON + MD + per-pair trade CSVs).

### Family verdict: **INCONCLUSIVE** — missing evidence, never promoted to a pass

| Pair | est. dates | active regimes | trades (IS/OOS) | net P&L | sample gate ≥20 |
|---|---|---|---|---|---|
| AUDUSDm/NZDUSDm | 87 | **0** | 0 / 0 | 0.0 | FAIL |
| EURUSDm/GBPUSDm | 87 | 3 | 0 / 1 | −0.0039 | FAIL |

**Gate diagnosis (why the regime is almost never active):** the AND of the
three preregistered gates on the same rolling 250-bar window is genuinely rare
on daily FX majors —

- AUD/NZD: ADF p<0.05 in **0/87** windows; cointegration p<0.05 in 9/87;
  joint (ADF ∧ coint ∧ HL-in-band) in **0/87**.
- EUR/GBP: ADF p<0.05 in 9/87; cointegration p<0.05 in 11/87; joint in
  **3/87** (all three also HL-in-band — the only windows that ever armed).

Median window p-values sit at ~0.25–0.48 — these pairs' log-price levels are,
on this data and at this estimation horizon, predominantly unit-root /
non-cointegrated by the preregistered standard. **The gates worked as
specified**: they refused to trade a relationship the statistics did not
support, rather than manufacturing one (the HYP-SA-001 failure mode the
contract explicitly banned).

**F-arm status:** F-A missing (insufficient OOS trades — permutation test not
run), F-B missing (no pooled OOS P&L), F-C computable and PASSED as a
diagnostic (family vs frozen-R4 replica daily-path correlation: **ρ = 0.0001**
over 1,826 overlap days — the (near-zero-traded) family is orthogonal to
momentum, consistent with the F-C rationale, but carries no standalone
evidence).

### Frozen interpretation (prevents later over-reading)

- **The correct reading is: under the preregistered gates, the two-pair
  family produced insufficient tradeable evidence to evaluate.** It is NOT
  "mean reversion doesn't exist in FX" and NOT "the gates are wrong."
- The near-zero active-regime count is itself **evidence about this data**:
  with daily bars and 250-bar windows, joint stationarity is rare. Any future
  exploration of gate calibration (window length, p-thresholds, HL band) is a
  NEW preregistration with new trial accounting — explicitly NOT a patch to
  rescue this one.
- The single EUR/GBP OOS trade (net −0.39%) is a diagnostic, not evidence.
- F-C's near-zero correlation is recorded as a **design observation** (the
  return-generating mechanism, when it trades at all, is not momentum), never
  as portfolio-utility evidence — there are no meaningful returns to combine.
- **One preregistered trial slot consumed by this INCONCLUSIVE family
  verdict.** No threshold search, no universe expansion, no gate re-tuning
  occurred, and none may follow without new preregistration.
- Frozen R4 production remains untouched (verified: nothing in this stage
  imports or modifies production code paths).

**Verification:** 685/685 research suite (20 new R4-MR tests: estimation
primitives vs theory anchors, PIT refusals, one-bar lag, cancellation,
force-close, cost math, determinism), ruff + mypy clean. During B1, one real
infrastructure correction: the estimation module's validation initially
enforced price positivity on LOG prices (wrong — log FX prices are negative);
positivity is a pre-log invariant enforced at the loader. Also fixed:
statsmodels added to the mypy stubs override.

**R4 status: A ✅ · B1 ✅ (INCONCLUSIVE recorded) — R4 COMPLETE.** The mean-
reversion family is **parked, not promoted and not killed**: reopening it
requires a new preregistration (candidate directions a future owner might
consider: intraday data, alternate estimation horizons, different pair
families — all NEW trials). Next in the frozen queue: **R5 — Triple-Barrier
Labeling** (label quality first, no ML).


---

## R4-B2 preregistration (frozen BEFORE any B2 code or data access)

**Status:** OPEN. One new preregistered trial slot (R4-B2) in response to
B1's gate starvation. The B2 hypothesis: the gate starvation observed in B1
was a *sample-size artifact of a two-pair universe*, not evidence that the
pipeline standard is miscalibrated. Under the UNCHANGED frozen pipeline, an
economically-motivated 8-pair family produces enough gate-pass episodes to
yield tradeable samples on this dataset.

**Universe (the ONLY change from B1).** Eight pairs selected by declared
economic rationale, stated here before any statistic is computed. No pair is
chosen by inspecting its cointegration results; equities are excluded
(912 bars from 2023 — cannot support 250-bar windows + OOS split):

| # | Pair | Declared rationale (ex ante) |
|---|------|------------------------------|
| 1 | AUDUSDm / NZDUSDm | carried over from B1 (commodity-currency bloc) |
| 2 | EURUSDm / GBPUSDm | carried over from B1 (European majors) |
| 3 | EURUSDm / USDCHFm | product = EURCHF; SNB/Eurozone policy linkage |
| 4 | USDCADm / USOILm | petro-currency (CAD tracks crude) |
| 5 | XAUUSDm / XAGUSDm | monetary metals, shared macro driver |
| 6 | US30m / US500m | same-market index pair, shared equity beta |
| 7 | USTECm / US500m | US equity vs tech-tilted index |
| 8 | BTCUSDm / ETHUSDm | shared crypto beta |

**Everything else frozen from B1, unchanged:** 250-bar rolling PIT window,
21-bar step, ADF p<0.05 ∧ cointegration p<0.05 ∧ half-life ∈ [5,60] gates,
z ±2.0 entries / ±0.5 exits, 60-bar z window, one-bar execution lag,
4×15 bps round-trip costs, IS/OOS split, verdict logic. NO modifications to
`estimation.py` or `pipeline.py`.

**Statistics:** one preregistered Holm family over the 8 pairs (sign-flip
arm F-A; F-B inapplicable below trade threshold; F-C recomputed as a pure
diagnostic only).

**Pre-committed parking rule (registered BEFORE execution):** if the 8-pair
family still yields fewer than 20 total trades across all pairs, the
mean-reversion family is PARKED on daily bars — no gate recalibration, no
window changes, no universe expansion beyond this set, no re-attempt on this
data class. Reopening requires a material data upgrade (intraday or
order-flow data), i.e., a new data class, not more attempts on the same wall.

**Falsification criteria:**
- F1: ≥1 pair produces ≥20 OOS trades and its mean signed return is not
  significantly > 0 after sign-flip permutation + Holm.
- F2: total trades < 20 across the family → parking rule fires (family
  parked; hypothesis remains unresolved-not-falsified on this data class).
- F3: any PIT/leakage defect found in execution → result discarded, bug
  fixed, experiment re-run under the same preregistration.

**Trial accounting:** ONE new slot (R4-B2) regardless of pair count; per-pair
Holm within the single family. Seed recorded at execution time in the result
artifact.

---

## R4-B2 status: COMPLETE — PARKED (parking rule fired) (2026-09-17)

**Execution:** `scripts/run_r4_b2_pairs.py` — the 8 preregistered pairs
through the UNCHANGED frozen B1 pipeline (zero modifications to
`estimation.py` / `pipeline.py`). Deterministic (permutation seed 42,
n=1000). Artifacts: `reports/r4_mean_reversion/r4_b2_pairs_report.json`,
`r4_b2_report.md`, per-pair trade CSVs.

**Result — the pre-committed parking rule FIRED:**

| Pair | active regimes | trades (IS/OOS) | net P&L |
|---|---|---|---|
| AUDUSDm/NZDUSDm | 0/87 | 0/0 | 0.0000 |
| EURUSDm/GBPUSDm | 3/87 | 0/1 | −0.0039 |
| EURUSDm/USDCHFm | 1/87 | 0/1 | −0.0129 |
| USDCADm/USOILm | 1/87 | 0/0 | 0.0000 |
| XAUUSDm/XAGUSDm | 1/87 | 0/0 | 0.0000 |
| US30m/US500m | 3/87 | 0/1 | +0.0048 |
| USTECm/US500m | 1/87 | 1/0 | +0.0111 |
| BTCUSDm/ETHUSDm | 1/104 | 0/1 | −0.1995 |
| **Total** | | **5** | **< 20 → PARKED** |

- Gate starvation is structural on daily bars under the preregistered
  standard: 0–3 active regimes per pair across ~87–104 estimation dates,
  even with 4× the universe. Quadrupling the universe produced only 5
  trades (B1 had 1) — the two-pair sample-size hypothesis is **rejected as
  an explanation**: the binding constraint is the standard itself
  (joint ADF ∧ cointegration at p<0.05 on daily windows), not universe size.
- **No pair reached ≥2 OOS trades** → the preregistered Holm family was not
  applicable; missing evidence stays missing (recorded, never imputed).
- F-C diagnostic (correlation with frozen-R4 replica daily path): ρ = 0.024
  — the (near-empty) family remains orthogonal to momentum.

**Disposition:** the mean-reversion family is **PARKED on daily bars**, per
the rule registered before execution. The hypothesis is **unresolved-not-
falsified on this data class**. Reopening requires a material data upgrade
(intraday or order-flow data) — a new data class, not more attempts on the
same wall. No gate recalibration, no window changes, no universe expansion
beyond this set, ever, on daily bars.

**R4 status: A ✅ · B1 ✅ (INCONCLUSIVE) · B2 ✅ (PARKED — rule fired) —
R4 CLOSED.** Next in the frozen queue: **R5 — Triple-Barrier Labeling**
(label quality first, no ML).

---

## Verification performed for R4-A

- All four data files read: identical 2,076-row coverage, consistent columns, no gaps observed at the boundaries checked.
- `statsmodels 0.14.6`: `adfuller`/`coint` import + smoke test passed (see Stage R4-A table).
- Governance registries + shadow correlation model: import-verified.
- `HYP-SA-001` inspected line-by-line (full_executor.py L126–166): confirmed NOT a cointegration pipeline; documented above; untouched.
