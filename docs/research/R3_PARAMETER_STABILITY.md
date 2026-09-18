# R3 — Parameter Stability / Robustness Study

**Date:** 2026-09-17
**Branch:** main · **HEAD:** 0b297a9
**Governing documents:** [RESEARCH_LITERATURE_AUDIT_REVIEW.md](RESEARCH_LITERATURE_AUDIT_REVIEW.md) §3 (parameter-stability reframe: pre-registered robustness study, multiple-testing risk named, "inside/outside stable region" output) · §14 stage-boundary table (R3: can modify R4 = **No**) · [R0_INFRASTRUCTURE_VERIFICATION.md](R0_INFRASTRUCTURE_VERIFICATION.md)

---

## R3 status: A — COMPLETE / FROZEN (this document, before any code)

**R3-B1 → NOT STARTED.** Everything below was recorded before implementation.

---

## R3-A: Infrastructure verification (code-level, verified by live import check)

| Component | Verdict | Evidence |
|---|---|---|
| Signal pipeline reuse | **PASS — reuse** | `scripts/export_r4_trade_stream.py` exposes `load_config_params`, `load_bars`, `compute_r4_signal`, `simulate_portfolio`; importable side-effect-free (main guarded). Grid runner imports these — **no signal-logic fork**. |
| Frozen parameters | **PASS** | `load_config_params()` verified live: lookback=252, skip=21, risk_lookback=20, vol_lookback=60, cost_one_way=0.0015 (config.toml). The grid center. |
| Walk-forward | **PASS — reuse** | `purged_walk_forward` (walk_forward.py): purge + embargo + anchored modes, window-independent geometry. |
| Sensitivity lens | **PASS — reuse** | `parameter_sensitivity` (sensitivity.py): per-axis plateau vs spike classification. A **view**, not a gate. |
| Multiple testing | **PASS — reuse** | `multiple_testing_correction` (Holm / BH / Bonferroni) — preregistered for the 5 grid axes. |
| False-confidence diagnostics | **PASS — reuse** | `compute_pbo` (pbo.py), `deflated_sharpe.py` — available for B1's evidence report. |
| Evidence gate | **PASS** | Falsification-first; missing evidence → INCONCLUSIVE. |
| Stability-surface framework | **GAP → B1 scope** | Region classification (STABLE / TRANSITIONAL / FRAGILE) + equity-curve production per grid point + preregistered region logic. No such module exists. |

**Conclusion:** R3-B1's new scope is exactly the region-classification framework + grid executor. Everything methodological already exists and is reused unchanged.

---

## Frozen R3 research contract (recorded before code)

1. **It is a robustness study, not a parameter search.** The output is never
   "optimal parameters are X". The output is exactly one of:
   **"the frozen configuration lies INSIDE a historically stable region"** /
   **"OUTSIDE"** / **"inconclusive"**. No recommendation output exists.
2. **The grid is pre-registered.** Axes, ranges, and step sizes are fixed in
   this document before the first grid point is evaluated. No ranges may be
   widened, shifted, or re-stepped after seeing results. Any such change = a
   NEW preregistration (new trial slots, fresh multiple-testing family).
3. **Bounded perturbations only.** Grid extends modestly around the frozen R4
   values — not a sweep to the boundary of plausible space. Ranges below are
   deliberately narrow.
4. **Frozen R4 is the grid center, never a grid point under test.** R4 itself
   is not modified, re-run, or re-fitted; it is the reference configuration.
5. **Every grid point = full pipeline.** Same data, same next-bar weekly
   execution, same cost model (one-way 15 bps), same simulator — only the
   parameters under perturbation differ. Data windows are identical across
   all grid points (no per-configuration data tuning).
6. **Per-point outputs (fixed before the first run):** CAGR, annualized vol,
   max drawdown, Sharpe (on the daily equity path), total net P&L, trade
   count, turnover, hit rate, payoff ratio. No post-hoc metric additions.
7. **WF-anchored evaluation where data permits.** `purged_walk_forward` on
   each point's equity curve (anchored, purge, embargo) — aggregate
   OOS-window statistics reported per point. Where a window geometry cannot
   fit, the point is reported with its reason (no silent drops).
8. **Multiple-testing is preregistered at the axis level.** Five axes, each
   axis's p-values (per-axis H₀: no monotone association between the
   parameter and performance across the grid — Spearman) enter ONE Holm
   family. A significant axis p-value is a flag that performance varies
   along that axis — a stability diagnostic, not a selection mechanism.
   No per-cell p-hacking; no cell is selected because it looks good.
9. **PBO and Deflated Sharpe are reported, not tuned.** Their role is
   false-confidence quantification. No selection uses them.
10. **No pass/fail thresholds beyond the preregistered.** The only
    preregistered criteria are the falsification criteria below. Everything
    else is descriptive. Percentiles of grid-point performance are statements
    about this experiment, not forecasts (same wording guard as B4 evidence
    report: experiment-statements, never future probabilities).
11. **Region classification is preregistered.** A grid point is classified:
    **FRAGILE** if its equity path is indistinguishable from a
    drawdown-dominated path (see falsification arm 2); **TRANSITIONAL** if
    adjacent to a FRAGILE point; **STABLE** otherwise. Adjacency = a
    neighbouring grid coordinate on any single axis (Moore/von-Neumann on the
    product grid). A region's stability is reported as the fraction of STABLE
    points in the connected component containing the frozen center.
12. **Report labels every number** as: OBSERVED (this dataset, this grid,
    these assumptions) — never as a property of future R4 behavior.

### Falsification criteria (preregistered, both must be answerable)

- **F1 — No stable region:** If the connected component of non-FRAGILE
  points containing the frozen center contains **< 60% STABLE fraction**
  (preregistered threshold) and the multiple-testing family flags ≥ 2 axes
  as performance-carrying, the study reports:
  **"the frozen configuration does not sit inside a historically stable region
  on this data"** — a legitimate, reportable outcome.
- **F2 — Center on a fragility boundary:** If the frozen center itself is
  FRAGILE or all its immediate neighbours are FRAGILE, the study reports
  exactly that — without recommending new parameters.

Failure conditions: post-hoc range changes; selective metric reporting;
treating the multiple-testing flag as a selection device; any output
expressed as parameter recommendations; any claim about future R4 behavior.

### Operational definitions frozen BEFORE grid execution (no post-hoc thresholds)

- **Point metrics, preregistered FRAGILE test:** a grid point is FRAGILE if
  **max_drawdown ≥ 0.40** (40% equity-path drawdown on this dataset) OR
  **Sharpe ≤ 0.0**. Both thresholds chosen before the first grid point is
  evaluated, on general grounds (a 40% drawdown or a non-positive Sharpe
  cannot be described as a stable configuration on a $-scaled equity path) —
  not from a preview of the grid distribution.
- **Adjacency:** two grid points are neighbours iff their coordinates differ
  by exactly one step on exactly one axis (von-Neumann adjacency on the
  product grid).
- **Connected component:** the frozen center's component = all points
  reachable from the center through sequences of pairwise-adjacent
  non-FRAGILE points.
- **STABLE fraction:** |STABLE points in component| / |component|, where
  component = non-FRAGILE reachable set; STABLE = non-FRAGILE and not
  adjacent to any FRAGILE point (TRANSITIONAL absorbs the boundary).
- **F1/F2 evaluation:** only after every grid point has a complete metric
  record; no partial-grid evaluation, no early stopping.

### Trial accounting

- The grid itself consumes **one registered trial family**
  (`R3-B1-grid-v1`) — the grid is preregistered as a unit; per-axis
  corrections happen within that one family. No grid-point shopping across
  re-registrations.

---

## Preregistered first experiment — R3-B1

| Item | Frozen value |
|---|---|
| Data | `data/mt5/*_D1.csv`, the 8 locally available R4-eligible symbols (identical windows across all grid points) |
| Universe version | `r4_local_v1` (same as R2-B1) |
| Grid axes (5) | `signal_lookback_long` ∈ {189, 220, **252**, 284, 315} · `skip_months` ∈ {0, 1, **2**, 3} (converted ×21 days) · `vol_lookback_signal` ∈ {40, 50, **60**, 70, 80} · `risk_lookback` ∈ {10, 15, **20**, 25, 30} · `rebalance_every` ∈ {3, 5 (frozen), 10} |
| Note on skip_months | Axis recorded in months; conversion ×21 trading days is frozen (r4_rebalance_loop convention). The frozen value (skip_months=1 → skip=21d) **is** a grid point — all five frozen parameter values sit inside their axes, which is what makes "is the frozen config inside a stable region?" answerable. skip=42/63 are research perturbations, never candidates. |
| Grid size | 5 × 4 × 5 × 5 × 3 = **1,500 points** (full factorial, no subsampling) |
| Costs | one-way 15 bps (config.toml 10 + 5) — identical across points |
| Seeds | n/a — no resampling inside R3-B1 (deterministic grid) |
| WF geometry | anchored, train=750, test=250, purge=10, embargo=5 (preregistered; windows that cannot fit are reported with reason) |
| Per-point metrics | CAGR, ann vol, max drawdown, Sharpe, total P&L, trades, turnover, hit rate, payoff (fixed list, contract item 6) |
| Multiple-testing family | ONE Holm family over the 5 axis-level Spearman p-values |
| Output semantics | OBSERVED-labeling; region map + stability fraction; PBO + Deflated Sharpe reported |
| Artifacts | `reports/r3_parameter_stability/r3_b1_grid_results.{json,csv}` + `r3_b1_report.md` |
| Runner | `scripts/run_r3_b1_grid.py` (imports the exporter's pipeline functions; zero signal-logic duplication) |

**Explicitly banned:** widening/shifting/re-stepping ranges after results;
dropping grid points post-hoc; adding metrics after the first run; selecting
parameters; any output language implying R4 modification; using the WF
aggregate as a selection score.

---

## Pre-execution addendum (recorded BEFORE the first grid point was evaluated)

- **Axis-level association test (contract item 8):** for each axis, Spearman
  correlation between the axis coordinate and the point's **full-path Sharpe**
  across ALL 1,500 grid points (marginal association, fixed definition).
  Two-sided p from the standard t-transform `t = ρ·√((n−2)/(1−ρ²))`, normal
  approximation via `math.erf` — the same convention as R2's IC p-value
  helper. The 5 p-values enter one Holm family (preregistered).
- **PBO application:** the 1,500 grid points ARE the candidate
  configurations; each contributes `(in_sample_sharpe, out_of_sample_sharpe)`
  from the preregistered WF geometry. `compute_pbo` defaults recorded
  (n_partitions=16, min_candidates=10). **Recorded caveat:** grid points
  share the same underlying data, so trials are not independent — PBO is
  reported as a false-confidence diagnostic with that caveat attached, never
  as a calibrated probability.
- **Deflated Sharpe application:** observed = the FROZEN CENTER's full-path
  Sharpe; n_trials = 1,500 (the one preregistered trial family);
  trial Sharpes = all grid points' full-path Sharpes (→ trial_sr_std);
  returns = center's daily path returns (moments derived by the
  infrastructure). **Same non-independence caveat as PBO.** Reported, not
  used for any decision.
- **Daily-path realization (preregistered):** per-point path metrics
  (CAGR, vol, max DD, Sharpe) and the WF equity input come from a
  close-to-close daily portfolio path built from the EXECUTED weight path
  (step function updated at weekly execution dates, one-day lag), minus
  per-change costs `|Δw| × cost_one_way`. Trade-level metrics (count, hit
  rate, payoff) come from the round-trip ledger. These are two documented
  realizations of one simulation; the trade ledger remains the R1-compatible
  artifact.
- **Execution:** deterministic multiprocessing (one worker per grid point,
  pure function of parameters + shared read-only data; no RNG anywhere in
  R3-B1). Worker count and wall-clock time recorded in the artifacts. A
  grid point that errors produces an explicit error record (symbol, params,
  exception) — never a silent drop.

## R3-B1 status: COMPLETE (2026-09-17)

**Execution:** 1,500/1,500 grid points evaluated, 0 errors, 56s wall on 14 fork
workers, deterministic (no RNG). Runner: `scripts/run_r3_b1_grid.py` reusing the
R1 exporter's `compute_r4_signal` / `simulate_portfolio` unchanged (zero
signal-logic duplication). Artifacts:
`reports/r3_parameter_stability/r3_b1_grid_results.{json,csv}` + `r3_b1_report.md`.

### Verdict (preregistered F2 arm)

> **OUTSIDE_STABLE_REGION** — *the frozen configuration itself classifies as
> FRAGILE on this data (preregistered thresholds); all its immediate grid
> neighbours are also FRAGILE — no recommendation is made.*

F2 fired before F1 could apply: the center's own point metrics (full-path
Sharpe **−0.246**, max DD 6.37%, 1,311 trades) breach the frozen FRAGILE
thresholds, and all von-Neumann neighbours are FRAGILE too. Component size 0,
stable fraction 0.0 — the F1 (fraction < 0.60 AND ≥ 2 flagged axes) machinery
was exercised and remains available, but was not the operative arm.

### OBSERVED findings (diagnostic, not verdicts on R4 production)

| Quantity | Value |
|---|---|
| Center full-path Sharpe | **−0.246** (annualized; per-period −0.0155) |
| Center max DD / trades | 6.37% / 1,311 (matches stream TS-R4-D1-0001) |
| Grid-wide Sharpe | min −1.113 · median −0.335 · max +0.222 |
| FRAGILE points | 1,380 / 1,500 (92%) |
| Axis associations (Holm) | risk_lookback ρ=+0.587, lookback ρ=+0.380, skip ρ=+0.231, vol_lookback ρ=+0.163 — all p≈0, flagged; rebalance_every ρ=0.000, p=1.0, unflagged (ρ=0 exactly: identical metric distributions across its values) |
| PBO | **1.000** (16/16 partitions: best-IS worst-OOS) + non-independence caveat |
| Deflated Sharpe | DSR 0.0019 (SR0 = 0.0478, n_trials = 1,500) — not significant |
| WF aggregate (center) | 5 windows, mean OOS Sharpe −0.306, 40% profitable |

### Frozen interpretation (prevents later over-reading)

- **This is a laboratory validation result about the replica pipeline on this
  dataset (8 symbols, r4_local_v1, one-way 15 bps), NOT a verdict on production
  R4.** The replica differs from the production loop by design (documented in
  the R1 exporter: point-in-time regime gate, weekly grid, subset universe);
  production R4-S forward/soak evidence is the decision path for production
  questions — nothing here touches it.
- The **preregistered robustness question is answered**: on this data and this
  grid, the frozen configuration does **not** sit inside a historically stable
  region, and its neighborhood is uniformly FRAGILE. That is a **falsifying
  observation for the stability hypothesis (H1)**, recorded as such.
  **Mandated sentence (frozen):** *the frozen configuration is not merely
  surrounded by a better configuration; the local neighbourhood itself fails
  the preregistered stability criterion.*
- **PBO phrasing guard:** within this laboratory, 16/16 partitions produced
  the PBO outcome — strong evidence against the stability hypothesis *under
  this particular PBO construction*. Because partitions are not fully
  independent, this must never be rhetorically upgraded (here or elsewhere)
  to "there is a 100% probability of overfitting".
- Axis associations are consistent with **monotone sensitivity in the
  lookback-family parameters** (longer lookback / longer skip / longer risk
  lookback → higher Sharpe within the preregistered ranges) — **recorded as an
  OBSERVED association, not a recommendation**. Selecting along any flagged
  axis would violate the frozen contract and re-open the optimization this
  experiment exists to avoid.
- The uniformly-flat rebalance_every axis is an OBSERVED artifact of the
  weekly-grid replica (weights are step-constant between execution dates), not
  a finding about rebalance frequency in production.
- PBO = 1.0 and DSR ≈ 0.002 are **false-confidence diagnostics with the
  recorded non-independence caveat** — reported, used for no decision.
- **No recommendation is made.** Any follow-up (e.g., a NEW preregistered
  experiment examining the lookback-family association) requires new trial
  accounting and cannot reuse this grid's evidence as justification.

**Verification:** 665/665 research suite (32 new grid tests), ruff + mypy clean.

**R3 status: A ✅ (contract frozen) · B1 ✅ (executed, verdict recorded) —
R3 COMPLETE.** Next in the frozen queue: **R4 — Mean Reversion / Stat-Arb
family** (small preregistered universe: AUDUSD/NZDUSD, EURUSD/GBPUSD).
