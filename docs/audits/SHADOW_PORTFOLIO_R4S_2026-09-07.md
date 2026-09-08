# R4-S Shadow Portfolio Construction — Forensic Research Report

**Date:** 2026-09-07
**Campaign:** R4-S (shadow-only portfolio-construction experiment alongside frozen R4)
**Git HEAD:** `aa6e629a3206d06dfdd58b74fdb99292ed51debd`
**Selector version:** `r4s-shadow-selector-0.1.0` (shadow package `0.1.0`)

**Executive verdict: CONTINUE SHADOW OBSERVATION. Do not promote.**

The shadow layer works exactly as designed — deterministic, no-lookahead,
execution-isolated, and R4 is byte-for-byte untouched. The empirical
evidence, however, does **not** yet support promotion: over the Jan–Aug 2026
replay window the correlation/exposure-aware portfolio halved maximum
pairwise correlation and cut portfolio volatility by ~22%, but it retained
only ~52% of R4's gross edge and its realized (as-if-traded) outcome was
**negative** (avg R −0.073). This is precisely the outcome the brief warned
about: *low correlation ≠ high quality*. The experiment stays in shadow.

---

## 0. Freeze discipline verification (brief §24)

| Check | Result |
|---|---|
| `git rev-parse HEAD` | `aa6e629a3206d06dfdd58b74fdb99292ed51debd` |
| `git diff -- configs/` | **EMPTY — `configs/` unchanged** |
| R4 signal / parameters / selection / sizing / risk gates / execution | **UNCHANGED** (no edits to `scripts/r4_rebalance_loop.py` or `scripts/r4_monitor.py`; see below) |
| R4 evidence schema (`decisions.jsonl`, `order_intents.jsonl`, `risk_gate_audit.jsonl`) | **UNCHANGED** — recorder refuses these filenames; byte-identity proven by test |
| Pre-existing local modifications | `scripts/r4_monitor.py`, `scripts/r4_rebalance_loop.py` were already modified **before** this task began; left untouched |
| Full test suite | **2939 passed, 1 skipped** (2842 non-dashboard + 97 dashboard), including 110 new shadow tests |
| `mypy src/eigencapital/shadow/` | clean |
| `ruff check` / `ruff format --check` (new code) | clean |

R4 decisions, R4 sizing, R4 risk gates, R4 execution, and the R4 evidence
schema are unchanged. Nothing in this work can reach a broker.

---

## A. Architecture assessment — where the shadow layer was attached

The frozen R4 pipeline (traced from `scripts/r4_rebalance_loop.py`):

```text
fetch_d1_data(mt5, R4_SYMBOLS, 300 D1 bars)
   ↓
compute_r4_signal(data)          → target_weights (full series, ±0.20 clip, BTC ±0.10)
   ↓  (regime gate: on/off)
generate_orders(target_weights, …)   → candidate universe (|w|>0.005, min-lot feasible)
   ↓
rank by |w| → take top MAX_CONCURRENT (20)      ← THE FROZEN R4 SELECTION
   ↓
RiskEnforcer gates → execute_orders (MT5) → order_intents.jsonl → decisions.jsonl
   (PortfolioAnalyzer already shadows analytics → portfolio_analytics.jsonl)
```

The shadow layer attaches **after `compute_r4_signal`, before the top-N cut**,
consuming the exact candidate universe R4 produces. It is a separate process
(`scripts/r4_shadow_portfolio.py`), which loads the frozen loop module
read-only (the same pattern `scripts/audit/reconstruct.py` already uses for
parity work), so:

- the frozen signal is **imported, not copied** — `replicate_signal()` in the
  runner is byte-for-byte parity-verified against `compute_r4_signal`
  (reconstruct.py C1 convention; asserted again in
  `test_r4_immutability.py::TestBaselineParity`),
- the shadow baseline is **R4's own selection** (opens from `generate_orders`),
  never a reimplementation guess (proven equal in tests),
- the shadow selector never sees a broker handle and never calls execution.

The production loop script was **not modified** (it was already dirty from
pre-existing user work and remains exactly as found).

## B. Existing infrastructure reused (no duplication)

| Capability | Reused from | Used as |
|---|---|---|
| Currency map + asset-class classification | `eigencapital.live.portfolio_analytics` (`SYMBOL_CURRENCY_MAP`, `CURRENCIES`, `ASSET_CLASS_MAP`) | imported directly |
| Shadow-analytics governance invariant | `live/portfolio_analytics.py` docstring (Phase 2 invariant) | adopted verbatim as the R4-S invariant |
| Shadow decision JSONL pattern | `live/risk_enforcement.py::record_shadow_decision` | recorder design |
| Frozen R4 signal + selection | `scripts/r4_rebalance_loop.py` (imported) | parity + baseline |
| Offline universe/CSV reconstruction | `scripts/audit/reconstruct.py` (frames, ratio/invert synthesis) | replay data path |
| Execution boundary vocabulary | `shadow/contracts.py` (ExecutionMode.SHADOW) | safety narrative |
| D1 histories | `data/mt5/*m_D1.csv` | correlation/vol/outcomes |

New code is confined to `src/eigencapital/shadow/portfolio/` (correlation,
exposure, metrics, selector, tracker) plus one runner script.

## C. Shadow selector design (mathematical + operational)

**Objective** (excess-over-threshold penalties; HHI deliberately excluded —
rewarding lower HHI rewards "more positions", which the brief forbids):

```text
quality(P) = gross_edge(P)
           − λ_risk · vol_annual(P)                       [λ=1.0]
           − λ_corr · corr_redundancy(P)                  [λ=0.5]
           − λ_ccy · max(0, max_currency_share − 0.5)     [λ=0.1]
           − λ_fac · max(0, max_factor_share − 0.5)       [λ=0.1]

corr_redundancy(P) = Σ_{p∈P} max(0, max_{q≠p} ρ_position(p,q) − 0.5)
ρ_position(a,b) = sign(w_a)·sign(w_b)·ρ_returns(a,b)
```

Key design decisions:

1. **Redundancy, not average correlation.** Average pairwise correlation
   saturates once a portfolio is already correlated, so a third identical
   copy stops changing it and the penalty vanishes. The redundancy term is
   linear in the number of correlated positions — each copy pays again.
2. **Direction-adjusted correlation.** LONG AUDUSD + SHORT GBPUSD with
   anti-correlated returns is the *same bet*; the sign product makes the
   penalty see it.
3. **Greedy marginal selection, deterministic.** Iterate candidates by
   |w| desc / symbol asc; add the candidate with the best positive marginal
   Δquality; stop when none improves. The chain P₁⊂…⊂Pₖ yields the
   N=1..k quality curve in one pass; the natural stop is the
   quality-maximizing cardinality. The selector is allowed to conclude
   NO_PORTFOLIO (expected edge insufficient) or NO_CANDIDATES.
4. **Edge proxy.** R4 exposes no return forecast; the signal weight
   (rank-centered, vol-scaled, clipped momentum) is the documented edge
   proxy. `gross_edge = Σ|w|`.
5. **Hard caps are redundancy caps** (currency 80% / factor 80% / asset-class
   100% of gross), firing only for multi-position portfolios — a singleton is
   concentrated by definition, so caps start at 2 positions.
6. **All hyperparameters** are config-driven, hashed into every decision
   (`config_hash`), isolated from frozen R4 config, and documented as
   experimental. λ sensitivity is future research.

## D. Exposure model

- **Currency:** FX pairs decompose to base/quote legs with sign from
  direction (LONG AUDUSD ≈ +AUD/−USD; SHORT EURUSD ≈ −EUR/+USD); single-leg
  instruments (indices, metals, crypto, energy — all USD-quoted) are treated
  as USD-exposed. Offsetting legs cancel at portfolio level.
- **Asset class:** canonical map from `live/portfolio_analytics` +
  documented single-leg entries (US30/USTEC/US500 indices, XAU/XAG metals,
  BTC/ETH crypto, USOIL energy).
- **Factor groups (diagnostic only, experimental):** equity_beta
  (US30/USTEC/US500/BTC), commodity (USOIL, AUD/NZD/CAD legs), safe_haven
  (XAU, JPY/CHF legs), risk_on (other FX), energy/metals. These are derived,
  lightweight tags recorded in evidence for clustering — **never** trading
  rules; correlation itself remains estimated from returns.
- **Clusters:** union-find on |corr| ≥ 0.7 (identical series land in one
  cluster) plus currency/factor concentration summaries; the largest cluster
  share of gross is reported per decision.

## E. Safety boundary (proven, not asserted)

1. **No execution path in the package** — AST-scanned: zero imports of
   broker/execution/MT5 modules; zero execution tokens
   (`order_send`, `submit_order`, `positions_get`, `execute_orders`,
   `emergency_flatten`, `TRADE_ACTION_DEAL`).
2. **Selector has no submission capability** — `ShadowSelector` exposes no
   broker, no order API, no submit method (asserted).
3. **Schema disjointness** — shadow decision records share no keys with
   order intents (side/quantity/order_type/ticket).
4. **Recorder refuses the four protected R4 evidence filenames**
   (`PermissionError`), proven byte-identical after shadow runs.
5. **Runner never calls execution functions** — AST-scanned; observe mode
   opens MT5 read-only (market data + symbol info only).

```text
Frozen R4 ──→ actual R4 orders                    (untouched)
Frozen R4 candidates ──→ Shadow Portfolio Constructor ──→ shadow decisions
      ──→ shadow tracking ──→ shadow_portfolio_*.jsonl   (NO broker path)
```

## F. Tests

Added `tests/unit/shadow/portfolio/` (110 tests; all pass, plus 17 pre-existing
`tests/unit/shadow/test_boundary.py`):

| Category | Coverage |
|---|---|
| Correlation | high / negative / zero / identical series, insufficient history, missing data, min-obs floor, regime-break stability, per-window averages, shrinkage PSD, config validation |
| FX exposure | same-currency stacking, offsetting exposures, long/short opposing, multi-currency, USD-quoted singles |
| Selection | strongest-signal retention, correlated-clone rejection, direction-aware anti-correlated redundancy, weak-uncorrelated entry, all-correlated, no candidates, fewer-than-N, NO_PORTFOLIO, currency hard cap, quality-by-N curve, conservative unknown-vol |
| Risk | cluster/currency/factor exposure, vol, HHI, div ratio, drawdown proxy |
| Determinism | same inputs ⇒ byte-identical decisions (json-stable); config hash stable + sensitive |
| No lookahead | as_of truncation hides planted future crashes; signal at t independent of later bars; tracker sees only caller-supplied prices |
| Safety | no execution imports/tokens, no submission capability, schema disjointness, recorder guards, runner AST scan |
| R4 immutability | signal identical with/without shadow import; baseline == `generate_orders` top-N; orders identical with shadow active; evidence files byte-identical |

## G. Historical / replay results (Jan 1 – Aug 24, 2026)

`python scripts/r4_shadow_portfolio.py --replay --start 2026-01-01 --end 2026-08-24 --fresh`
— 236 trading days, 136 regime-on decision days, daily decisions (reconstruct
C4 convention; weekly cadence is a documented sensitivity).

| Metric | R4 (20 positions) | Shadow (avg 5.97, 1–8) |
|---|---:|---:|
| Gross edge (Σ\|w\|) | 1.053 | 0.505 (52.1% retained; min 15.8 / max 79.9) |
| Max \|pairwise corr\| | 0.891 | **0.463** (−48%) |
| Avg \|pairwise corr\| | 0.040 | 0.013 |
| Portfolio vol (ann., weight space) | 0.086 | **0.067** (−22%) |
| HHI / effective positions | 0.104 / 9.68 | 0.430 / 3.90 |
| Diversification ratio | 2.39 | 1.76 |
| Max corr-cluster share of gross | 0.486 | 0.516 |
| Max currency share | 0.363 | 0.534 |
| Max factor-group share | 0.473 | 0.589 |

**Realized shadow outcomes (as-if-traded, weight-space PnL proxy):**
125 closed positions; total PnL **−337.4**, avg R **−0.073**, hit rate 49%.
Worst month Apr (−262.7); best May (+13.1). **The shadow portfolio lost
money in this window** — the diversification did not improve realized
outcomes. Correlation estimates were also visibly unstable
(cross-window stability avg 0.141), so trusting a single static correlation
view would be unwise.

**Limitations (honest):** offline replay approximates min-lot feasibility by
config eligibility (no broker specs in CSV); entry/exit at decision-day
close per reconstruct C8; no transaction costs in shadow PnL; the frozen
R4 *realized* series for the identical window is not present in this
checkout (`reports/r4_economics_audit/` artifacts are absent), so a direct
R4-vs-shadow realized comparison must wait for live R4-S soak evidence.
No walk-forward/λ-sensitivity split was performed yet — that is required
before any promotion claim.

## H. Live R4-S observations

Not yet run. `--observe` is implemented and read-only (single-cycle and
`--loop` soak on the trading host). Replay above is the pre-live evidence
generator; every replayed cycle produced a full provenance record (136
decisions, 125 outcomes) in:

```text
reports/r4_loop/shadow_portfolio_decisions.jsonl
reports/r4_loop/shadow_portfolio_outcomes.jsonl
```

Each decision records cycle id, signal date, candidate universe (with
per-candidate vol, rank, rejection reason, marginal quality), baseline R4
selection, shadow selection, quality-by-N, edge retention, full metrics,
correlation metadata (windows, stability), selector version + config hash.
Replay is **byte-deterministic** across runs (proven: identical decisions and
outcomes files, timestamps excepted).

## I. Universe findings (resolves the BTCUSD/XAUUSD question)

1. The screenshot universe (BTCUSD, XAUUSD, USOIL, USTEC, US30) is the
   **current production universe** — `[broker.allowed_symbols]` in
   `configs/production/config.toml` (33 entries), filtered by the loop's own
   eligibility rule (`not endswith("_excluded")`). It is the production R4
   universe, not a research-only one.
2. **BTCUSD IS reachable from the production R4 path**: it is
   `"crypto"` (eligible), and the frozen signal carries a BTC-specific
   ±0.10 clip (`compute_r4_signal` step 6) — the forensic order-pipeline
   audit (2026-09-01) documents this explicitly, and `docs/architecture/
   SYSTEM_TRUTH.md` lists the current universe as "21 FX, 1 metals, 1
   indices, 1 energy, 1 crypto".
3. **XAUUSD IS part of the frozen production universe** and eligible
   (min lot $4,627 fits the $5K cap).
4. The recollection that "crypto was removed from production" is **stale**
   relative to the current frozen config; the research/fidelity manifest
   (`fidelity/r4_manifest.py`) is a different (research) universe, which is
   probably the source of the confusion.
5. **Doc drift found (not fixed — freeze):** the `[capital]` comment
   "12 tradeable instruments out of 15 (USDJPY, XAUUSD, XAGUSD, US30
   excluded)" contradicts the symbol comments (XAUUSD/US30 fit the $5K cap)
   and runtime eligibility. Flagged as a documentation finding only.
6. No universe/configuration mismatch was found between config and the
   runtime loop. The shadow selector consumes whatever universe R4 produces;
   it did not modify the universe.

## J. Promotion recommendation

**CONTINUE SHADOW OBSERVATION.**

Quantitative basis:
- **Risk reduction is real but incomplete**: max |corr| −48%, portfolio vol
  −22%, avg |corr| 0.040→0.013. Concentration shifted (HHI 0.10→0.43; max
  currency/factor shares *increased* with fewer positions) and the
  corr-cluster share of gross did not improve (0.486→0.516) — fewer
  positions means one cluster holds a larger fraction.
- **Alpha preservation failed in-sample**: edge retained only 52%, and
  realized shadow outcome was **negative** (−0.073 avg R). The
  "diversification thrown away the alpha" scenario is the live possibility.
- **Robustness not established**: no walk-forward split, no λ/correlation-
  window sensitivity, correlations are unstable (0.141 avg cross-window Δ).

Required before re-evaluation: (1) R4-S live soak ≥ 30 days with the same
cycle granularity as live R4; (2) walk-forward split with λ sensitivity;
(3) transaction-cost stress on shadow turnover; (4) a same-window R4
realized comparison (from the live loop's own order intents + fills).

**R4 remains the control group. R4-S stays shadow-only. Architecture frozen.**

---

### Appendix — artifacts

```text
src/eigencapital/shadow/portfolio/
    __init__.py        public API + governance invariant
    correlation.py     no-lookahead rolling correlation model (20/60/120)
    exposure.py        currency/asset-class/factor exposure + hard caps
    metrics.py         shared R4-vs-shadow portfolio metrics
    selector.py        deterministic greedy shadow selector + provenance
    tracker.py         decision/outcome JSONL persistence + as-if-traded tracking
scripts/r4_shadow_portfolio.py   --replay | --observe | --status [--fresh]
tests/unit/shadow/portfolio/     110 tests (7 files)
reports/r4_loop/shadow_portfolio_decisions.jsonl   (136 records)
reports/r4_loop/shadow_portfolio_outcomes.jsonl    (125 records)
```

`configs/` unchanged. R4 evidence files untouched. No commit was made.