# R5 — SWING BREADTH: PRE-REGISTERED CAMPAIGN

**Status:** 🔒 PRE-REGISTERED 2026-08-25 — before any R5 evaluation result exists.
**Information source:** Exness MT5 daily bars (D1), frozen snapshot
`R5_SWING_BREADTH_D1`, combined_sha256 `3d10cf9322bda6cd9f5d4966a53e4d8d`
(38 instruments, per-file hashes in `data/mt5/R5_data_manifest.json`).
**Authority:** this document. Code that deviates from it is wrong.
Derived from the hypothesis library (`research/hypotheses/README.md`) and the
ML4T extraction; governed by RESEARCH_ENGINE_CONTRACT.md.

---

## Why this campaign

The intraday OHLCV branch is falsified and frozen (133 evals); the tick
microstructure branch produced no survivor under hardened governance (72
evals). The book-aligned growth vector (Jansen 2020 — whose validated-by-
example territory is daily-horizon factor research) is **breadth in the
swing lane**: test the dormant families of the pre-registered library on a
38-instrument universe with the upgraded validation machinery (per-flip net
accounting, purged+embargoed walk-forward, IC diagnostics, family-wise
correction, cumulative trial accounting, DSR).

## Cumulative trial ledger (daily lane)

| Campaign | Evaluations |
|---|---|
| R2 risk transformations | 16 |
| R3 freeze variants | 4 |
| R4 strategies A–G | 7 |
| **Prior total** | **27** |
| **R5 family (this campaign)** | **16** |
| **Cumulative after R5** | **43** |

Any SUPPORTED verdict must additionally satisfy deflated-Sharpe significance
computed against N = 43 (and against any larger future ledger) before
promotion beyond research status.

## Universe & point-in-time membership

All 38 snapshot instruments. Histories are staggered (22 US equities begin
2023-01-03; macro/asset-class names from 2020). Membership intervals derive
from actual data availability via `UniverseMembershipRegistry`
(`effective_from` = first bar date, open interval). Cross-sectional
strategies use `members_as_of(date)` ONLY — no look-ahead universe
construction. This is the first production consumer of the survivorship
layer; its registry file is written at data-freeze time and hashed with the
snapshot.

## The locked slate — 16 hypotheses, one primary configuration each

Horizon-shopping is prohibited: each hypothesis carries exactly ONE primary
holding horizon chosen by mechanism ex ante. Sensitivity variants may be
reported as diagnostics but are never gate-relevant.

| # | ID | Mechanism (exact signal) | Primary horizon / rebalance | Family gate group |
|---|---|---|---|---|
| 1 | TREND-001 | TS momentum: sign(return_252d − return_21d skip), i.e. 12−1m | 21d hold, weekly rebalance | trend |
| 2 | TREND-002 | Price acceleration: Δ(vol-adjusted 63d trend slope) > 0 long, < 0 short | 21d hold, weekly | trend |
| 3 | TREND-003 | Distance from 52w high: long if within 20% of high, else flat | 21d hold, weekly | trend |
| 4 | MOM-001 | Cross-sectional momentum: rank 126d return, long top tercile − short bottom tercile among members as-of date (min 12 names, else flat) | 21d hold, weekly | cross_sectional |
| 5 | MOM-002 | Volume-normalized momentum: rank(126d return ÷ √mean tick_volume²¹ᵈ), L/S terciles as MOM-001 | 21d hold, weekly | cross_sectional |
| 6 | MR-001 | Short-term reversal: short 21d winners / long losers within members (terciles), inverse sign of MOM-001 ranking window | 5d hold, weekly | mean_reversion |
| 7 | MR-002 | RSI(14): long RSI<30, short RSI>70, flat between (Wilders smoothing) | 5d hold, daily check | mean_reversion |
| 8 | MR-003 | Asset-class relative value (re-labelled from sector-relative): z-score vs asset-class basket mean (63d), fade ±2σ extremes | 10d hold, weekly | mean_reversion |
| 9 | BRK-001 | 52w breakout: long new 252d-high close, exit on close < 63d low | 10d hold, event-driven exits | breakout |
| 10 | BRK-002 | Range expansion: (high−low)/ATR₁₄ > 1.5σ above its 63d mean → follow direction of bar | 5d hold | breakout |
| 11 | VOL-001 | Low-vol anomaly: long bottom-tercile 63d vol − short top tercile, among members | 21d hold, weekly | volatility |
| 12 | VOL-002 | Beta tilt: long bottom-tercile beta (vs equal-weight member basket, 126d) − short top tercile | 21d hold, weekly | volatility |
| 13 | VOL-003 | Vol-of-vol regime: std of 21d rolling vol (63d window) below its 25th pct → hold base basket momentum ×1, above 75th → ×0 | regime overlay on TREND-001 | volatility |
| 14 | SA-001 | Engle–Granger pairs: top absolute-|corr| pair per asset class cluster (126d window); OLS hedge ratio refit 63d rolling; trade z±2 in / z±0.5 out on spread | until z-exit or 63d stop | stat_arb |
| 15 | SA-003 | Correlation-clustered pairs: greedy clustering at |ρ|≥0.8 (126d), best in-cluster EG-qualifying pair, same trade rule as SA-001 | same | stat_arb |
| 16 | FACTOR-001 | PCA eigenportfolios: correlation matrix of member returns (252d), PC1 = market sleeve; long PC1-weighted basket when its own 63d trend > 0, else flat | 21d hold, weekly | factor |

Excluded from this campaign (recorded, with reasons): MOM-003 analyst
revisions (no data); CS-001/002/003 fundamentals (no PIT fundamentals);
SA-002 Johansen (hand-rolled eigenvalue tests too error-prone — deferred);
SA-004 Bayesian hedges (PyMC unavailable); FACTOR-002 vague scope;
FACTOR-003 FF replication (no factor data); ML-001/002 (gated behind
interpretability + no sklearn/lightgbm in deps); ALT-001..003 (no sources).

## Validation protocol (frozen)

1. **Accounting:** `net_accounting.bt_net` — one-way cost charged per flip
   inside the series. Base = 15 bps round-trip equivalent (7.5 bps/side),
   adverse = 25 bps (12.5 bps/side), uniform across asset classes
   (conservative for FX, optimistic for some equities — recorded honestly).
   Annualization: bars_per_trading_day=1, trading_days_per_year=252.
2. **Walk-forward:** `purged_walk_forward` with purge=5, embargo=5,
   train=504d/test=126d sliding windows; require ≥3 windows.
3. **Permutation:** anchor-instrument / equal-weight-member-basket
   significance, 500 permutations, on the NET series.
4. **Family-wise correction:** all 16 evaluations form ONE Bonferroni
   family. SUPPORTED requires p_adj_family ≤ 0.05.
5. **Cumulative ledger:** p_adj_cumulative = min(1, p_raw × 43) reported;
   SUPPORTED further requires p_adj_cumulative ≤ 0.05, else downgrade to
   FRAGILE with reason `cumulative_trial_weakness`.
6. **Deflated Sharpe:** every survivor gets DSR (Bailey–López de Prado)
   vs N=43 with returns-derived moments; significant=True required for any
   promotion claim beyond this report.
7. **Frozen gates (all must pass):** corrected net Sharpe ≥ 0.50 (base AND
   adverse ≥ 0.30); WF consistency ≥ 50%; permutation p_adj ≤ 0.05;
   max DD > −25% on net series; instrument breadth ≥ 30% positive (where
   applicable); degradation ≤ 2.0×; no single-year dependence (positive in
   ≥ 60% of years).
8. **Diagnostics (non-gating):** IC series + quantile spreads for
   cross-sectional hypotheses (#4,5,6,11,12); year/session-less regime
   table; sensitivity variants reported but never selected upon.

## Prohibited actions

Parameter tuning after first result; adding/removing hypotheses mid-run;
re-running with modified costs/windows to change a verdict; promoting any
survivor without DSR significance and independent forward confirmation on
freshly collected D1 data; touching the frozen R4 lane.

## Decision rule

Zero survivors → swing-breadth branch recorded as null evidence; library
statuses updated to REJECTED; next breadth attempt requires a new
pre-registration with materially different information content.
Survivor(s) → C-analogue confirmation campaign on post-snapshot data before
any fidelity-ladder entry.
