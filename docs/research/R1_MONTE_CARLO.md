# R1 — Monte Carlo Diagnostics

**Date:** 2026-09-17
**Branch:** main
**HEAD:** 0b297a9
**Governing documents:** [RESEARCH_LITERATURE_AUDIT_REVIEW.md](RESEARCH_LITERATURE_AUDIT_REVIEW.md) §9 (R1), §12 (H₀ correction) · [R0_INFRASTRUCTURE_VERIFICATION.md](R0_INFRASTRUCTURE_VERIFICATION.md) (PATCH item → input adapter)

---

## Research hypothesis (frozen, per review §12)

> **H₀:** Under the specified resampling mechanism, the observed historical path is statistically consistent with the distribution of alternative paths generated from the same trade population.

We are **not** testing "does Monte Carlo prove R4 will be profitable?" — that is methodologically wrong. We are asking: **how sensitive is the observed R4 path to trade sequencing and sampling variation?**

> **Methodological rule (not a falsification criterion):** Monte Carlo outputs are *conditional diagnostics under the simulation assumptions*, never forecasts of future returns.

---

## Phase A — Trade-Stream Persistence (this document)

Per the R1 handoff: the first commit is deliberately boring — **trade-stream persistence + schema + provenance + deterministic round-trip tests**. Monte Carlo (Phase B) then sits on a clean, reproducible input rather than reaching backward into transient `BacktestResults`.

### Architecture position

```text
R4 BACKTEST → BacktestResults.fill_events
    → [Phase A: adapter] → PERSISTED TRADE STREAM (schema + provenance hash + JSON)
    → [Phase B: MC engine] → path distributions → R1 evidence report
```

### What was built

| File | Role |
|------|------|
| `src/eigencapital/research/monte_carlo/schema.py` | `TradeRecord` + `TradeStream` frozen dataclasses with strict invariants and canonical SHA-256 provenance hash |
| `src/eigencapital/research/monte_carlo/persistence.py` | `save_trade_stream` / `load_trade_stream` — canonical JSON round-trip with load-time tamper detection |
| `src/eigencapital/research/monte_carlo/adapter.py` | `backtest_results_to_trade_stream` — conservative pairing of `fill_events` into closed round-trips |
| `src/eigencapital/research/monte_carlo/__init__.py` | Public API surface |
| `tests/unit/research/monte_carlo/test_trade_stream.py` | 33 unit tests |

### Schema invariants (enforced, not documented)

- Trade indices contiguous 1..N in order (deterministic ordering).
- Exit timestamps monotonic non-decreasing across the stream.
- Every trade closed: `entry_timestamp <= exit_timestamp`.
- P&L and cost values finite; costs non-negative; side ∈ {LONG, SHORT}.
- Strict parsing: unknown/missing fields rejected at load (provenance integrity).
- Provenance hash = SHA-256 (via `eigencapital.core.provenance`) over identity fields (schema version, stream id, experiment, strategy, dataset, git commit, cost model) + every trade record. Recomputed and verified on every load; `save` refuses to write a stream whose stored hash does not match its content.

### Adapter conservatism rules

- Fills must strictly alternate open/close (BUY-before-SELL = LONG, SELL-before-BUY = SHORT). Pyramiding/scaling is **rejected**, not silently coerced.
- Odd fill counts / unmatched trailing fills are **rejected** — MC input must be closed trades only; no evidence is silently dropped.
- Per-trade P&L is **supplied by the caller**, never re-derived from fill prices — no ambiguity about which P&L definition produced the stream. Explicit per-trade costs may also be supplied; default is the paired fills' commission + fees.
- Instrument is required (explicitly or via fill events).

### Verification results

| Check | Result |
|-------|--------|
| Unit tests (schema invariants, round-trip, determinism, tamper detection, adapter) | **33 passed** |
| Full research test suite (`tests/unit/research/`) | **539 passed** — no regressions |
| `ruff check` + `ruff format` | Clean |
| `mypy` on the new package | Success, no issues |

Tamper detection verified by test: value edits, trade removal, and trade reordering in a persisted file are all caught at load time by the recomputed provenance hash.

### Scope discipline

- Research-only: no changes to R4, risk engine, execution, or any production boundary (frozen review §14).
- Reused existing contracts: `eigencapital.core.provenance` hashing (per audit §25 "reuse existing contract over create new framework"); `BacktestResults.fill_events` shape as-is.
- Phase B (permutation / bootstrap / block bootstrap on the persisted stream) is the next step; `analytics/validation/block_bootstrap.py` already exists and will be reused, not rebuilt (R0 finding).

---

## Phase B1 — Trade-Sequence Permutation (COMPLETE / FROZEN 2026-09-17)

No further additions to B1 unless a concrete defect appears.

Scope discipline honored: B1 only. Bootstrap (B2) and block bootstrap (B3) are deliberately not implemented in this step.

### What was built

| File | Role |
|------|------|
| `research/monte_carlo/path_metrics.py` | `compute_path_metrics` — one ordering → max drawdown (fraction of running peak), drawdown duration (longest underwater run in trades), longest losing streak, recovery time, min equity, time-under-water, total P&L, trade count |
| `research/monte_carlo/permutation.py` | `run_permutation_test` — seeded permutations of the trade ORDER, per-ordering path metrics, distributions, quantiles, historical percentiles |
| `tests/unit/research/monte_carlo/test_permutation.py` | 22 unit tests |

### The frozen B1 invariant, enforced numerically

> Pure permutation preserves the exact set of trades. Set-dependent metrics (total P&L, trade count) are invariant; path-dependent metrics can change.

Every permutation run verifies total P&L and trade count against the historical path and raises on violation (`set_invariance_verified` in the result). Tests confirm path-dependent metrics genuinely vary across permutations while the set does not.

### Honest handling of "never recovered"

`recovery_time` is `None` when a path draws down but never regains its pre-drawdown peak within the observed trades. None is never coerced to a number: percentiles treat it as strictly worse for higher-is-worse metrics; quantile reports carry an explicit `n_never_recovered` count alongside quantiles computed over finite observations only.

### H₀ stays frozen

The engine answers: *how sensitive is the observed path to trade ordering?* It does not and cannot ask whether R4 is profitable. Output serialization carries the methodological rule verbatim (`"NOT a forecast"`), and historical metrics + percentiles are reported under an explicit `historical` key separate from `simulated_distributions`.

### Frozen B1 interpretation (prevents later over-interpretation)

> **B1 tests sensitivity of realized path diagnostics to trade ordering while holding the realized trade population fixed. It does not test sampling uncertainty, future profitability, parameter robustness, or overfitting.**

Two corollaries recorded with it:

- **Total P&L invariance is a sanity check, not a result about strategy quality.** The research information in B1 is the *dispersion of the path-dependent metrics* around the historical path — where the observed ordering sits inside the ordering distribution.
- **B1 cannot say whether the original trade sample itself is representative.** That is exactly the question B2 (IID bootstrap) is designed to investigate, by deliberately breaking the fixed-population invariant.

### Verification results

| Check | Result |
|-------|--------|
| Monte Carlo unit tests (Phase A + B1) | **55 passed** |
| Full research suite (`tests/unit/research/`) | **561 passed** — no regressions |
| `ruff check` + `ruff format` | Clean |
| `mypy` | Success, no issues |

Notable test behaviors: wins-first orderings score high historical percentiles on max drawdown; losses-first orderings score low (both by construction); identical seeds reproduce identical distributions.

---

## Phase B2 — IID Bootstrap (COMPLETE / FROZEN 2026-09-17)

Same-size commit as B1; reuses `TradeStream` and `path_metrics.py` unchanged.

### What was built

| File | Role |
|------|------|
| `research/monte_carlo/bootstrap.py` | `run_bootstrap_test` — IID resample WITH replacement (duplicates/omissions intended), per-resample path metrics, distributions, quantiles, historical percentiles |
| `tests/unit/research/monte_carlo/test_bootstrap.py` | 15 unit tests |

### The deliberately different invariant vs B1

B1 holds the realized trade population fixed (total P&L invariant, enforced). B2 breaks it on purpose: the sampled sequence may contain duplicates and omissions, so **total P&L is expected to vary**. The result object records this explicitly as `set_invariance_expected = False`. Tests confirm the contrast: B1 distributions contain no sample-dependent metrics, B2 collects `total_pnl` and `final_equity` alongside the path-dependent set, and resamples of an all-winning trade set still show P&L dispersion (duplicates vs omissions).

Sample size defaults to the historical trade count and is overridable; the position of the realized total P&L / final equity inside the resampling distribution is the headline sample-uncertainty diagnostic.

### IID caveat (recorded, drives B3)

Independent-with-replacement resampling destroys serial clustering. If R4's outcomes are regime-dependent, IID bootstrap understates path risk relative to block bootstrap. B2 output therefore feeds *comparison* with B3, not standalone conclusions.

### Verification results

| Check | Result |
|-------|--------|
| Monte Carlo unit tests (A + B1 + B2) | **70 passed** |
| Full research suite | **576 passed** — no regressions |
| `ruff check` + `ruff format` | Clean |
| `mypy` | Success, no issues |

Notable test behaviors: an outlier trade (500 vs 1s) stretches the P&L distribution exactly as IID theory predicts; `recovery_time=None` is preserved and counted (`n_never_recovered`); identical seeds reproduce identical distributions.

---

## Phase B3 — Block Bootstrap (COMPLETE 2026-09-17, contract frozen before implementation)

### Frozen conceptual contract (recorded BEFORE implementation)

> **B3 tests sampling uncertainty while preserving contiguous short-run trade dependence through block resampling. It does not test future profitability, parameter robustness, overfitting, or regime stationarity.**

The implementation answers exactly one question: **does the evidence materially change when the IID assumption is relaxed?** Not: "does B3 produce a better-looking distribution?" This distinction matters enormously when B4 compares B1/B2/B3.

### Implementation contract (frozen before code)

1. **Pre-specified block length.** Block length is itself a methodological choice; introducing several candidate sizes and selecting the most favorable risk distribution would be a new researcher degree of freedom. B3 therefore takes a **required, pre-specified `block_length` argument** (no default, no search). Alternative block-length sensitivity is a separate later study only if evidence warrants it. The chosen length and the construction method are recorded in the result provenance.
2. **Moving-block construction** (standard, defensible starting point): build all contiguous blocks of length L from the historical sequence, sample blocks **with replacement**, concatenate until the requested sample length is reached, truncate to exactly that length.
3. **Contract boundary vs B1/B2:**

   ```text
   B1: same trades exactly once        → total P&L invariant
   B2: trades sampled with replacement → duplicates/omissions → total P&L varies
   B3: blocks sampled with replacement → blocks duplicated/omitted
                                       → individual trades duplicated/omitted
                                       → total P&L varies
   ```

   B3 exposes `set_invariance_expected = False` (like B2) plus block-specific metadata fields (`block_length`, `block_method="moving_block"`), making the three resamplers structurally comparable rather than three subtly different implicit contracts.
4. **Same shared machinery:** provenance refusal, seeded reproducibility, `None`-preserving recovery semantics, `"NOT a forecast"` labeling, historical-vs-simulated separation.
5. **Validation rule:** `block_length >= 1` and `<= n_trades`; `n_resamples >= 1`; quantiles in [0, 1].

### What was built

| File | Role |
|------|------|
| `research/monte_carlo/block_bootstrap.py` | `run_block_bootstrap_test` (block_length REQUIRED, no default) + `moving_block_sample` pure resampler; result carries `block_length` / `block_method="moving_block"` / `n_blocks_per_resample` / `set_invariance_expected=False` |
| `tests/unit/research/monte_carlo/test_block_bootstrap.py` | 19 unit tests |

### Contract honored in code and tests

- **Pre-specified block length:** the argument is required with no default; out-of-range values are rejected with a message stating the no-search rule. Block-size selection was not performed; block-length sensitivity would be a separate later study.
- **Moving-block construction verified:** every output window of length L provably appears in the historical sequence; truncation to exact sample size tested.
- **Clustering preservation demonstrated:** on a loss-clustered stream (runs of identical values), the block resampler reproduces intact within-block runs that IID resampling would make extremely unlikely, and its max-drawdown q95 exceeds B2's on the same stream — the quantitative form of "does the evidence change when IID is relaxed?"
- **Structural comparability:** B3 exposes the same fields as B2 plus block metadata; B1/B2/B3 now share one explicit contract family (invariant / expected-to-vary / expected-to-vary-with-dependence).

### Verification results

| Check | Result |
|-------|--------|
| Monte Carlo unit tests (A + B1 + B2 + B3) | **89 passed** |
| Full research suite | **595 passed** — no regressions |
| `ruff check` + `ruff format` | Clean |
| `mypy` | Success, no issues |

---

## Phase B4 — Combined Evidence Report (COMPLETE 2026-09-17)

**Aggregation only — no new methodology.** B4 consumes the historical stream + B1/B2/B3 results and produces ONE reproducible artifact. It invents no new test, no pass/fail thresholds, no percentile-to-probability conversion.

### What was built

| File | Role |
|------|------|
| `research/monte_carlo/evidence.py` | `build_evidence_report` + `render_markdown` — the six frozen questions answered per metric; three mandatory labels (OBSERVED HISTORICAL PATH / RESAMPLED DIAGNOSTIC DISTRIBUTION / INTERPRETATION) enforced in structure and rendering; wording guard printed in every report |
| `scripts/run_r1_evidence_report.py` | Runner: loads the persisted stream, runs B1/B2/B3 (seeds recorded, block length pre-specified) → JSON + MD artifacts |
| `tests/unit/research/monte_carlo/test_evidence.py` | 19 unit tests |
| `reports/r1_monte_carlo/r1_evidence_report.{json,md}` | First evidence artifact (TS-R4-D1-0001) |

### Design points honored

- **No pass/fail:** tests assert no pass/fail/verdict vocabulary in the artifact.
- **Wording guard:** every report renders the Correct/Incorrect percentile-wording pair; interpretation lines use only experiment-percentile language.
- **Honest B1 gap:** B1 percentiles are `n/a (invariant)` for set-invariant metrics (total_pnl, final_equity) — the artifact records that no percentile exists rather than manufacturing one.
- **Block metadata prominent:** `Block length: 20 (pre-specified) | Blocks per resample: 66` displayed in the report with the no-tuning note.
- **Scope guard:** the report describes exactly the consumed stream (id, period, 1,311 trades, provenance) and states it is NOT a claim about R4's long-run behavior.
- **Consistency guard:** refuses to build when B1/B2/B3 disagree on the historical metrics (not run on the same stream/parameters).

### First evidence findings (TS-R4-D1-0001, n=1000 per resampler, seed 42, block length 20)

- Historical max drawdown (9.25%) sits at the **27% / 44% / 42%** percentile of the B1/B2/B3 resampled drawdown distributions — a statement about the experiments run, not about the future.
- **Stable across assumptions:** max_drawdown, max_drawdown_duration, recovery_time, time_under_water, total_pnl, final_equity (historical percentile spread within tolerance).
- **Changed when dependence is retained:** recovery_time, longest_losing_streak, max_drawdown — B3's adverse q95 exceeds B2's (e.g. longest losing streak +4.95 trades at q95). IID resampling understates these tails for this stream; that difference itself is evidence, reported without forcing it into pass/fail.

### Verification results

| Check | Result |
|-------|--------|
| Monte Carlo unit tests (A + B1–B4) | **108 passed** |
| Full research suite | **614 passed** — no regressions |
| `ruff check` + `ruff format` | Clean |
| `mypy` | Success, no issues |

---

## R1 STATUS: COMPLETE

The full methodological ladder is built and evidenced on real R4 output:
**order sensitivity (B1) → IID sampling uncertainty (B2) → dependence-aware sampling uncertainty (B3) → combined evidence artifact (B4)**, on top of the provenance-stamped trade-stream boundary (Phase A).

Every component: research-only, provenance-gated, seeded/reproducible, honestly labeled (diagnostics, never forecasts). Next stage per the frozen queue: **R2 — Alpha Factor Laboratory** (R0 confirmed `factor_evaluation.py` — IC / Rank IC / quantiles / turnover — already exists and will be reused, not rebuilt).

---

## Phase B4 — Distribution / Evidence Report (NOT STARTED)

After B3: combined evidence report across B1/B2/B3 with the historical-vs-simulated distinction enforced in output labeling.

---

## First Real Trade Stream (2026-09-17)

The trade-stream boundary is proven end-to-end on real R4 output.

### Runner

`scripts/export_r4_trade_stream.py` — a **research exporter**, not the production loop. Faithfulness notes (all documented, none silent):

- Signal is a replica of `scripts/r4_rebalance_loop.py::compute_r4_signal` (the canonical R4 pipeline): 12-1 momentum (252/21), cross-sectional rank centered at 0, point-in-time regime gate (20-day avg vol < expanding median), 60-day vol scaling vs 50% reference, final clip ±0.20. Parameters read from `configs/production/config.toml`.
- Execution: next-bar open, weekly rebalance. Costs: 10 bps + 5 bps slippage per leg (config.toml) = 30 bps per round trip.
- The production loop evaluates the regime gate at the latest bar; the exporter applies it point-in-time (anti-lookahead requirement). BTCUSD tightening is irrelevant (no local history). 8 of 17 eligible symbols have local data (documented limitation).
- The adapter is called per symbol (its pairing contract is a single strictly-alternating fill sequence); per-symbol trades are merged exit-chronologically and re-indexed 1..N — satisfying the schema's exit-monotonic invariant for a multi-symbol portfolio.

### Stream

| Property | Value |
|----------|-------|
| Stream ID | `TS-R4-D1-0001` |
| Location | `reports/r1_monte_carlo/trade_stream_R4_daily.json` |
| Period | 2020-01 → 2026-08 (local MT5 D1) |
| Round-trips | 1,311 across 8 symbols |
| Win rate | 501/1311 (38%) |
| Total net P&L | −0.0756 (return units) |
| Historical max DD / longest loss streak | 9.25% / 15 |
| Provenance | verified on save AND on reload (round-trip identity asserted) |

### First diagnostic results (500 permutations / resamples, seed 42)

| Diagnostic | Value |
|------------|-------|
| B1 percentile (max_drawdown) | 0.279 |
| B2 percentile (total_pnl) | **0.507** |
| B2 total_pnl q05 / q50 / q95 | −0.1327 / −0.0765 / −0.0104 |

**Theory check (recorded):** B2's resampled median total P&L (−0.0765) sits almost exactly on the historical value (−0.0756) and the historical percentile is 0.507 ≈ 0.5 — precisely where bootstrap theory places the observed sample statistic within its own resampling distribution. The machinery behaves as specified.

**Interpretation (per the frozen methodology):** these numbers are *conditional diagnostics under the resampling assumptions*. They say the observed path is entirely typical of its own resampled distribution (B2) and mildly benign on ordering (B1). They are NOT evidence of future profitability, and the negative total P&L is not a strategy verdict — it reflects an 8-of-17-symbol subset without the production universe, weekly-grid rebalancing, and interval-close trade realization. Reading any promotion decision into it would violate the frozen stage-boundary table (review §14).

---

## Phase B — MC Engine (ORIGINAL PLAN, superseded by B1–B4 sequencing)

Planned (frozen review §9 R1): permutation/shuffle, bootstrap, block bootstrap → drawdown / losing-streak / recovery / terminal-wealth / underwater-duration distributions → R1 evidence report with historical-vs-simulated distinction enforced in output labeling.
