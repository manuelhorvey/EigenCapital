# Volatility Taxonomy & Trade-Path Research

**Status:** Descriptive/diagnostic research artifact — COMPLETE
**Config version:** `vol_taxonomy_v1`
**Git commit at generation:** `43ba779`
**Governing contracts:** `docs/RESEARCH_ACCOUNTING_CONTRACT.md` · `docs/DATA_CONTRACT.md` · `docs/research/DATA_REQUIREMENTS.md` (fail-closed verdicts, Holm-corrected families, costs inside returns, PIT)
**Package:** `research/volatility/` (15 modules, SHA-256 pinned in `reports/volatility_taxonomy/reproducibility.json`)
**Artifacts:** `reports/volatility_taxonomy/{taxonomy_results,trade_path_results,evidence_ledger,reproducibility}.json`
**Tests:** `tests/unit/research/volatility/` — **48/48 PASS** · full suite (`tests/unit` + `tests/property`) — **3340 passed, 2 skipped, 1 failed, 17 warnings (334s)**. The single failure — `tests/unit/live/test_rebalance_policy_loop_integration.py::TestRestartNoDoubleTrade` (assert TRADE vs HOLD) — is **pre-existing at HEAD `43ba779`**: verified by stashing all work in this branch and re-running (same failure). It is unrelated to this research (live rebalance loop; no imports from `research/volatility`).

**Production boundary:** This document opens no trial slot, registers no hypothesis, and must never be cited as authorization for a production change. No file under `scripts/`, `data/mt5/`, `src/eigencapital/` (behavioral), live trading, risk, sizing, or execution was modified.

---

## Table of contents (§62 structure)

1. Research question · 2. Governance status · 3. Universe · 4. Data sources · 5. PIT/data-integrity verification · 6. Methodology · 7. Volatility features · 8. Volatility regimes · 9. Volatility clustering · 10. Temporal stability · 11. Cross-asset synchronization · 12. Trade-level dataset · 13. MAE/MFE analysis · 14. Time-to-profit analysis · 15. Underwater-duration analysis · 16. Oscillation analysis · 17. Path-efficiency analysis · 18. Volatility × trade-path interaction · 19. Low-volatility hypothesis tests · 20. Within-asset tests · 21. Cross-asset tests · 22. Holding-period controls · 23. Cost analysis · 24. Robustness · 25. Falsification · 26. USOIL incremental analysis · 27. Copper incremental analysis · 28. Redundancy analysis · 29. Limitations · 30. Evidence classification · 31. Production boundary · 32. Reproducibility record

Appendices: **A** §50 executive Q&A · **B** §51 asset-level volatility table · **C** §52 trade-path table · **D** §53 regime-conditional (population) · **E** §54 volatility × trade-path matrix · **F** §64 final questions

---

## 1. Research question

> Does EigenCapital's current volatility structure explain differences in how trades travel — particularly the apparent tendency of lower-volatility conditions to oscillate more, remain underwater longer, and take longer to realize directional movement — and are those effects robust enough to justify any future research direction?

Chain: OBSERVATION → FORMAL HYPOTHESIS → MEASUREMENT → NORMALIZATION → WITHIN-ASSET → CROSS-ASSET → ROBUSTNESS → FALSIFICATION → EVIDENCE CLASSIFICATION.

## 2. Governance status

| Item | Determination |
|---|---|
| Classification | **Descriptive infrastructure + diagnostic research** (DATA_REQUIREMENTS steps 1–3) |
| Experiment registration | **Not required, not opened** — no trial slot consumed |
| Frozen program conflict | **None** — analysis reads frozen artifacts; never writes to `scripts/`, `data/mt5/`, production |
| Inferential claims | Holm step-down inside pre-declared families (`config.H_FAMILIES`); otherwise descriptive |
| Fail-closed rule | Missing evidence → INCONCLUSIVE / INSUFFICIENT DATA, never a pass |

## 3. Universe

Frozen baseline = the 34-asset `ASSET_CLASSES` dict (indices ×2, metals ×2, energy ×1, crypto ×1, forex ×28). USOIL and Copper are **external candidates only** — never part of the baseline, never production. No silent additions (ETH, Brent, other crypto/index/commodity) were made.

## 4. Data sources

Order of trust (each hash-verified at load):

1. `data/mt5/` frozen R5 D1 snapshot — `R5_data_manifest.json`, combined SHA-256 `3d10cf9322bda6cd9f5d4966a53e4d8d3a6563a748cb25e685bdf54157b898f1`
2. `data/taxonomy_d1/` supplement (22 baseline assets) — own frozen manifest
3. `data/candidates/` Copper (yfinance HG=F front future, documented provider) — own frozen manifest

Trade population: PIT replay of the frozen R4 signal (`scripts/export_r4_trade_stream.py` imported unmodified).

## 5. PIT / data-integrity verification

- All 36 loaded frames pass: monotonic timestamps, no duplicates, positive prices, OHLC hierarchy, no NaN OHLC (`data.py::_validate_frame`, raises `DataIntegrityError`).
- Windows (taxonomy features): primary 2022-06-01 → 2026-08-24 (covers XNGUSD from 2022-03-20 + 60-bar warmup); robustness 2020-06-01 → 2026-08-24 (33 assets, XNGUSD excluded). Trade stream window is longer — see §12.
- Trade fills: **strictly next day after signal** (`searchsorted side="right"`) on **each symbol's own calendar** (XAUUSD weekday gaps vs FX; union calendar produced NaN — exclusion, not imputation).
- Documented defect in frozen exporter: fills at open of signal date while weights use that date's close (one-bar lookahead). **Not patched** — frozen stream kept as robustness comparator only (`TS-R4-D1-0001`).
- Entry regime labels use only information strictly before the entry bar (expanding percentile / expanding z — both PIT).
- Zero coverage warnings at load; integrity report: 36 assets, 0 dupes.

## 6. Methodology

- Estimators conformance-tested against canonical Bar primitives (`test_features_equivalence.py`).
- Clustering: 9-component robust-scaled feature vector → Euclidean distance → average linkage → k = silhouette maximizer over {2..6}, ties → smaller k.
- Declared sensitivities: Ward, correlation-distance of log RV, PCA(2)+k-means (seed 42).
- Stability: chronological thirds, ARI vs full labels, co-membership, feature-distance correlation.
- Trade path: reconstructed from D1 bars between entry and exit fills; side-aware MAE/MFE in return space; exit-bar intrabar extremes included (daily granularity, documented).
- Multiple testing: every comparison increments a ledger counter; p-values Holm-corrected within families before any verdict.
- All constants frozen in `research/volatility/config.py` (LARGE_MOVE_K_SIGMA=3.0, INITIAL_PHASE_BARS=3, MIN_CELL_TRADES=20, RANDOM_SEED=42, SIGMA_HALF_SIGMA=0.5).

## 7. Volatility features

Canonical: RV = sample variance (ddof=1) of close-to-close log returns × √252. Horizons RV_5/10/20/60. Range-based: Parkinson, Garman-Klass, ATR/price (all annualized × √252 where applicable). Persistence: AC1 of RV, |r|, r². Vol-of-vol: std and CV of RV_20, 21-day RV change. Tails: skew, excess kurtosis, q01/q99, downside/upside 5/95, extreme freq |r| > 3σ_1y. Jump **proxies**: freq |r| > 3×RV_20 daily, mean ratio, RV-spike freq (>1.5× trailing 63-bar median). Estimator dispersion: mean absolute log-ratio across RV/PK/GK. Full definitions in `features.py` docstrings.

## 8. Volatility regimes

Two constructions, both computed:

1. **Percentile (within-asset):** LOW < P25, NORMAL P25–75, HIGH P75–95, EXTREME > P95. Full-sample variant = descriptive structure only; **expanding (PIT) variant** used for all trade conditioning.
2. **Z-score of log(RV)** vs trailing 252 (min 60): cuts at −1 / +1 / +2. Always PIT.

Transitions: row-normalized first-order matrices (descriptive, no causality). Runs: count, mean/median/p90/max duration per regime. Example: XAUUSD spends 14.9% in EXTREME (mean run 8.4 bars) vs XNGUSD 2.3% (mean run 9.7) — occupancy ≠ mean level.

## 9. Volatility clustering

Primary cut **k=2** (silhouette 0.730; table k=2..6: 0.730 / 0.679 / 0.451 / 0.412 / 0.357):

- **Cluster 1 (n=32):** all forex, US30, USTEC, BTCUSD, XNGUSD
- **Cluster 2 (n=2):** XAUUSD, XAGUSD

PCA: PC1 = 61.8%, PC2 = 13.5%, 5 components for 90%. Robust scaling = median/IQR per feature.

## 10. Temporal stability

| Third | Bounds | k | ARI vs full |
|---|---|---|---|
| early | 2022-06-01 → 2023-10-29 | 2 | −0.039 |
| middle | 2023-10-30 → 2025-03-27 | 2 | 0.234 |
| recent | 2025-03-28 → 2026-08-24 | 2 | 0.380 |

**Verdict: UNSTABLE** (ARI_min = −0.04 < 0.5). Co-membership across 497 pairs: mean 0.85, min 0.00. Feature-distance stability early vs recent: 0.19. Method sensitivities at the full-window cut: ARI = 1.000 for Ward, correlation-distance, and k-means — **method-robust within the window, not time-invariant**. Leave-one-out: ARI_min = 1.000 for all 34 removals (no structurally influential asset).

## 11. Cross-asset synchronization

Top log-RV correlations: AUDJPY–NZDJPY 0.91 · CADJPY–USDJPY 0.89 · AUDUSD–NZDUSD 0.89 · EURJPY–GBPJPY 0.88 · CHFJPY–EURJPY 0.87. Weakest: EURCAD–XAGUSD −0.30 · EURJPY–XAGUSD −0.21. Joint HIGH|EXTREME occupancy: XAGUSD–XAUUSD 0.254 (highest), US30–XAUUSD 0.128, USTEC–XAUUSD 0.126. Return-space correlations computed and stored **separately**, never used as volatility-similarity proxies. No causal claim.

## 12. Trade-level dataset

| Property | Value |
|---|---|
| Population | **1,311** closed round-trips, 0 skipped path reconstructions |
| Window | entry 2020-10-28 → 2026-08-03, exit → 2026-08-09 (R4 signal uses full R5 history from 2020-06-01 + 252-bar warmup; distinct from the taxonomy feature window of §5) |
| By symbol | AUDUSDm 167 · EURUSDm 167 · GBPUSDm 152 · NZDUSDm 151 · USDCADm 167 · USDCHFm 173 · USDJPYm 167 · XAUUSDm 167 |
| Side | LONG 744 / SHORT 567 |
| Params | lookback 252, skip 21, risk_lookback 20, vol_lookback 60, rebalance_every 5, cost_one_way 15 bp (frozen R4) |
| Clock | bar dates from broker D1 files; fills at next-day open on own calendar; exit-bar close for terminal |
| Fields per trade | asset, side, signal/entry/exit ts+px, weight, net/gross P&L, costs, holding, entry RV & PIT percentile & regime, MAE/MFE (raw + σ-normalized), time-to-events, underwater (price + net), oscillation, path efficiency, trade type, large-move flags |

## 13. MAE/MFE analysis

Side-aware, return-space; exit-bar extremes included. Population: MAE median 0.68% (mean 0.90%), MFE median 0.68% (mean 0.96%); in σ units: MAE median 1.74σ, MFE median 1.77σ. Per-asset medians in Appendix C — XAUUSD has the largest σ-normalized MFE median (2.32) and smallest σ-normalized MAE median (1.49) among the eight traded assets. P25/P75/P90/P95 stored per cell in `trade_path_results.json`.

## 14. Time-to-profit analysis

- Median time-to-first-profit = **1 bar** (mean 1.56); p75 = 2 bars.
- **24.7% NO_PROFIT_BEFORE_EXIT** (censored, never coded as 0).
- Time-to-MFE: median 4 bars (p25 2, p75 6).
- By entry regime: median time-to-first-profit = 1 in LOW/NORMAL/HIGH; censor rates 23.9% / 25.8% / 21.6% — no monotone gradient. EXTREME: INSUFFICIENT DATA (n=0).

## 15. Underwater-duration analysis

Definition: unrealized asset return u = d·(px/entry − 1) < 0 at path closes (price path, pre-cost); net variant requires u > 2×one_way to count as out. Population: max-underwater-run mean 2.36 bars (median 2), underwater fraction median 0.40 (price) vs **0.80 (net-of-cost)** — costs roughly double the share of bars spent red on the net definition, but the entry-RV relation is absent in both (§19, F5).

## 16. Oscillation analysis

Entry-crossing count = sign changes of non-zero (px − entry); P&L sign changes on non-zero u; crossings/bar median 0.0, mean 0.123, p75 0.167. Path length / net displacement → efficiency in §17. Holding is almost always 6 bars (weekly schedule): medium bucket n=1,305 with H1 ρ inside bucket = **+0.0008** (p=0.977) — the pooled null is not hiding a holding-bucket artifact.

## 17. Path-efficiency analysis

path_efficiency = |exit − entry| / path_length. Mean 0.477, median 0.438, p25 0.220, p75 0.734. Medians by asset 0.41–0.45 (Appendix C) — no asset materially more "meandering" than another at the median.

## 18. Volatility × trade-path interaction

Resolution-speed buckets (ex-ante, strategy geometry: fast ≤1 bar, moderate 2–3, slow ≥4, no_profit = null):

| Entry regime (PIT pctile) | n | fast | moderate | slow | no_profit | med ttf | med uw-run |
|---|---|---|---|---|---|---|---|
| LOW | 606 | 0.523 | 0.175 | 0.063 | 0.239 | 1 | 2 |
| NORMAL | 631 | 0.512 | 0.179 | 0.051 | 0.258 | 1 | 2 |
| HIGH | 74 | 0.514 | 0.203 | 0.068 | 0.216 | 1 | 2 |
| EXTREME | 0 | — | — | — | — | — | **INSUFFICIENT DATA** |

Shares are flat across rows (Appendix E). Z-score regime table: identical qualitative result; EXTREME n=6 → INSUFFICIENT DATA.

## 19. Low-volatility hypothesis tests

Direction frozen ex-ante: lower entry RV percentile ⇒ longer underwater / more oscillation / slower resolution ⇒ **negative** Spearman ρ. X = expanding PIT entry RV percentile (min 250).

**Pooled (Holm family m=4):**

| H | Metric | n | ρ | p_raw | p_Holm | Verdict |
|---|---|---|---|---|---|---|
| H1 underwater | max_underwater_run | 1,290 | +0.005 | 0.856 | 1.00 | **INCONCLUSIVE** |
| H2 oscillation | crossings/bar | 1,290 | +0.009 | 0.745 | 1.00 | **INCONCLUSIVE** |
| H3 time-to-first-profit | first_profit_bar | 977 | −0.009 | 0.780 | 1.00 | **INCONCLUSIVE** |
| H4 time-to-MFE | time_to_mfe | 1,288 | +0.026 | 0.358 | 1.00 | **INCONCLUSIVE** |

**Controls:** H5 normalization **NOT SUPPORTED** (raw MAE ρ = +0.064 vs σ-normalized MAE ρ = **−0.161, p ≈ 5.5e-9** — sign does not persist; underwater_fraction ρ = −0.002, p = 0.94). H6 periods **UNSTABLE** (frac negative across thirds = 0.56; thirds are trade-window splits 2020-10-28→2021-12-24, →2024-05-31, →2026-08-03 — distinct from the §10 feature-window thirds). H7 holding-period partial ρ: all four ≈ 0 → **INCONCLUSIVE**. No-profit rate by RV quartile is non-monotone (Q1 0.260, Q2 0.224, Q3 0.248, Q4 0.238) — no low-vol gradient.

**Overall combined claim: NOT SUPPORTED** (H1 direction wrong after Holm + 9/12 battery failures). Interpretive note: σ-normalized adverse excursion *is* larger when entry vol percentile is low (mechanical sense: absolute MAE scales with vol), but the behavioral claim — longer underwater, more oscillation, slower resolution — has no supporting association.

## 20. Within-asset tests

8 assets × 4 metrics = 32 Holm-corrected within-asset tests: **0 SUPPORTED**, sign-consistency frac_negative = 0.50. F1/F12: the pooled null is not an aggregation artifact of opposite within-asset effects — half the within-asset ρ are negative, half positive, none significant after Holm. **If the phenomenon exists only cross-sectionally and not within assets, it would be asset-specific; here it exists in neither place.**

## 21. Cross-asset tests

After σ-normalization (mae_sigma/mfe_sigma): see H5 — normalized MAE has a significant *negative* ρ with entry percentile (low-vol entries have larger adverse moves relative to their own daily σ), yet normalized MFE likewise (ρ = −0.145, p ≈ 1.6e-7), and neither translates into underwater-duration or time-to-resolution differences. When volatility is comparable, trade-path *duration* behavior does not differ systematically by entry regime.

## 22. Holding-period controls

- Modal holding = 6 bars (weekly rebalance); short (<6) and long (>6) buckets n=3 → INSUFFICIENT DATA.
- Within the 6-bar bucket: H1 ρ = +0.0008 (p = 0.977).
- H7 rank-residual partial ρ on holding bars: H1 +0.001, H2 +0.011, H3 −0.008, H4 +0.025 — all INCONCLUSIVE.

## 23. Cost analysis

Canonical cost model unchanged (2 × 15 bp × |w|). Per-asset median cost / median MFE: XAUUSD 0.20 · AUDUSD 0.38 · NZDUSD 0.40 · GBPUSD 0.45 · USDJPY 0.47 · USDCHF 0.51 · EURUSD 0.52 · USDCAD 0.64. Fraction of trades where asset-space cost exceeds MFE: 9%–31% (XAUUSD lowest, EURUSD/USDCHF highest). Mean net P&L ≈ −0.0001 per trade for the seven FX pairs, +0.00017 for XAUUSD. F5: ρ(price-path underwater) = +0.005 (wrong direction) vs ρ(net-of-cost) = −0.031 — the net variant is slightly negative but the price-path object of the hypothesis already fails directionally; costs do not manufacture the red period pattern claimed by the observation.

## 24. Robustness

| Axis | Alternative | Result |
|---|---|---|
| Estimator | ATR-percentile entry vol (F9) | H1 ρ = +0.011 — same null |
| Regime definition | Expanding z(log RV) (F10) | H1 ρ = +0.008 — same null |
| Regime labels | z-score vs percentile PIT | Flat matrix rows both ways |
| Sample | Chronological thirds (H6) | UNSTABLE signs |
| Extreme trades | 1% trim (F7) | ρ = +0.0003 — null |
| Sessions | FX-only subset (F6) | ρ = +0.001 — null |
| Costs | Price vs net-of-cost (F5) | Neither supports claim |
| Estimator dispersion | PK/GK vs RV | Stored per asset; no verdict change |
| Frozen stream | TS-R4-D1-0001 comparator | Same n=1,311; lookahead version not used for claims |

## 25. Falsification (F1–F12)

| # | Check | Result | Key number |
|---|---|---|---|
| F1 | within-asset | survives | frac_negative = 0.50 (weak, but ≥0.5) |
| F2 | normalization | **fails** | H5 NOT SUPPORTED |
| F3 | holding period | **fails** | frac partial-ρ negative = 0.25 |
| F4 | strategy | inconclusive | single strategy population by design |
| F5 | costs | **fails** | ρ_price = +0.005 |
| F6 | sessions | **fails** | ρ_fx = +0.001 |
| F7 | extremes | **fails** | ρ_trimmed = +0.0003 |
| F8 | periods | **fails** | H6 UNSTABLE |
| F9 | estimator | **fails** | ATR H1 ρ = +0.011 |
| F10 | regime definition | **fails** | z-logRV H1 ρ = +0.008 |
| F11 | large-move (k=3σ) | **fails** | ρ(time-to-large) = **+0.144** (opposite) |
| F12 | cross vs within | survives | mirrors F1 |

**9 fail · 2 survive · 1 inconclusive.**

## 26. USOIL incremental analysis

**STRUCTURALLY REDUNDANT.** k stays 2; baseline-label ARI = 1.00; joins cluster 1; nearest baseline neighbor USTEC at d = 2.62 (inside baseline p75 = 4.83); silhouette Δ = −0.038. No new regime archetype, no trade-path uniqueness claim (not in trade population — candidate never traded by the R4 replay).

## 27. Copper incremental analysis

**STRUCTURALLY DISTINCT.** Singleton cluster on insertion; baseline-label ARI = 0.00 (labels reshuffle); nearest neighbor USDCHF at d = 7.83 (outside p75 envelope); silhouette Δ = +0.12; distance to both baseline centroids > 8. Occupies a region of volatility-feature space no baseline asset occupies. Economic difference ≠ statistical novelty is *rejected here on measurement*: the novelty is measured, not assumed.

## 28. Redundancy analysis

- **Volatility space:** feature-distance matrix + RV/log-RV/|r| correlations + regime co-occurrence in `taxonomy_results.json → similarity`. Nearest pairs (log-RV): JPY crosses and commodity-bloc pairs (§11).
- **Trade-path space:** separate standardized-median distance over (ttf, underwater, mae_sigma, mfe_sigma, crossings/bar, efficiency, uw-fraction). Nearest path neighbors: EURUSD↔GBPUSD (1.37), NZDUSD↔USDCAD (2.13), AUDUSD↔USDJPY (2.02), XAUUSD↔EURUSD (2.52).
- **Cluster ↔ path link:** cluster 1 (7 traded members) vs cluster 2 (XAUUSD only in population): medians ttf 1 vs 1, uw-run 2 vs 1, uw-frac 0.60 vs 0.40, win 0.502 vs 0.611, mfe_sigma 1.70 vs 2.32. The metals' distinct *volatility* cluster maps to milder underwater runs and higher win rate in-path — descriptive only (n=1 asset in cluster 2's path sample).

## 29. Limitations

1. Single strategy population (frozen-R4 replica) — F4 explicitly inconclusive for strategy effects.
2. Eight traded assets (7 FX + XAUUSD) — no BTC/XNG/index trade-path coverage; cross-asset path questions limited to that set.
3. D1 granularity: intrabar extremes approximated by daily high/low; exit-bar extremes included.
4. Frozen exporter lookahead defect (documented, not patched); primary population is the PIT-corrected replay.
5. EXTREME entry-regime cells: n = 0 (pctile) / n = 6 (z) → INSUFFICIENT DATA — no claim about EXTREME-path behavior.
6. Primary window ~4.2 years; temporal stability measured only over three thirds of that window.
7. Copper/USOIL analyzed in volatility space only (not in trade population).
8. H5 nuance: σ-normalized MAE/MFE *are* significantly higher at low entry percentile, but this is excursion scale, not path duration — the observation claims duration/oscillation, which fail.

## 30. Evidence classification

| Object | Classification |
|---|---|
| Full-window k=2 cut | Method-robust (ARI=1.0 vs 3 sensitivities); descriptive for the window |
| Temporal membership | **UNSTABLE** |
| LOO structure | Stable (ARI_min = 1.0) |
| USOIL | **STRUCTURALLY REDUNDANT** |
| Copper | **STRUCTURALLY DISTINCT** |
| H1–H4 pooled | **INCONCLUSIVE** (all) |
| H5 | **NOT SUPPORTED** |
| H6 | **UNSTABLE** |
| H7 | **INCONCLUSIVE** |
| Combined low-vol trade-path claim | **NOT SUPPORTED** |
| F4 (strategy) | INCONCLUSIVE by design |
| EXTREME-regime path cells | **INSUFFICIENT DATA** |

## 31. Production boundary

- **Descriptive only:** all taxonomy tables, regime structures, similarity matrices, cluster labels.
- **Robust negative research finding:** the low-vol trade-path hypothesis as stated does not survive measurement — usable to *deprioritize* a future hypothesis slot, not to change any rule.
- **Requires separate registered experiments before any production thought:** anything in §56 of the brief (wider stops, longer holds, sizing, exclusions, thresholds) — **none of which are implied or authorized here.**

## 32. Reproducibility record

| Item | Value |
|---|---|
| Config | `vol_taxonomy_v1` |
| Git commit | `43ba779` |
| Python / numpy / pandas / scipy / sklearn | 3.14.7 / 2.3.5 / 2.3.3 / 1.17.1 / 1.8.0 |
| Manifests | R5 `3d10cf93…` + supplement + candidates (frozen) |
| Package hashes | 15 × SHA-256 in `reproducibility.json` |
| Windows | primary 2022-06-01→2026-08-24; robustness 2020-06-01→2026-08-24 |
| Seeds | RANDOM_SEED=42 (k-means only; everything else deterministic) |
| Bar frequency / clock | D1, tz-naive broker dates (declared-UTC convention) |
| Trade dataset | PIT_R4_D1_REPLAY_V1, 1,311 trades |
| Evidence counters | 1,311 comparisons · 4 clustering configs · 34 LOO · 2 candidates · 2 Holm families |
| Analysis timestamp | see `reproducibility.json → generated_at_utc` |

```bash
python -m pytest tests/unit/research/volatility/ -q   # 48 passed
python -m pytest tests/unit tests/property -q         # 3340 passed, 2 skipped, 1 pre-existing failure (see header)
python -m research.volatility.runner                   # writes reports/volatility_taxonomy/
```

---

## Appendix A — §50 executive answers

1. **What volatility archetypes exist?** At the full-window primary cut: two — a metals pair (XAU/XAG) and everything else. Finer k (3–6) has much weaker silhouette (≤0.68).
2. **How stable are they?** UNSTABLE across time (ARI_min −0.04); method-stable within the window (ARI 1.0 vs Ward/corr/k-means); LOO-stable (ARI 1.0).
3. **Which assets cluster together?** 32 assets cluster 1; XAUUSD+XAGUSD cluster 2. Within cluster 1, nearest feature neighbors include US30↔USTEC, XAG's NN = XAU, BTC's NN = USDJPY (level-adjusted space).
4. **Is BTC structurally distinct?** No — cluster 1, LOO non-influential; mean RV 0.378 but robust-scaled features place it inside the main blob (NN USDJPY).
5. **Is XNG structurally distinct?** No — cluster 1 (despite highest mean RV 0.498); NN EURNZD; LOO non-influential. Distinct for *level*, not for *shape* features.
6. **Do XAU/XAG form a stable group?** Together in every window's k=2 cut (both sides of the split are the metals); group membership is the most persistent pair, but ARI instability means the *boundary* moves elsewhere.
7. **Do US30/USTEC form a stable group?** Same cluster (1); rv_corr 0.91, log-RV 0.81; mutual nearest feature neighbors.
8. **Do JPY crosses form a stable group?** All seven in cluster 1; highest log-RV pair correlations in the universe are JPY crosses (AUDJPY–NZDJPY 0.91 etc.); empirically coherent, not hard-coded.
9. **Does USOIL add new volatility information?** No — STRUCTURALLY REDUNDANT.
10. **Does Copper add new volatility information?** Yes — STRUCTURALLY DISTINCT (singleton, ARI 0.0, outside distance envelope).
11. **Evidence for the low-vol trade-path hypothesis?** No — combined claim NOT SUPPORTED; H1–H4 INCONCLUSIVE; 9/12 falsifications fail.
12. **Does it survive normalization and controls?** No — H5 NOT SUPPORTED, H7 INCONCLUSIVE, H6 UNSTABLE, holding-bucket H1 ρ ≈ 0.
13. **What remains inconclusive?** H1–H4 individually (absence of evidence for a wrong-signed effect); F4 strategy confound; EXTREME-regime path cells (INSUFFICIENT DATA); trade-path novelty of candidates (never traded).

## Appendix B — §51 asset-level volatility table

Cluster stability applies at group level (see §10); NN = nearest neighbor in feature distance.

| Asset | Class | Mean RV | CV | RV AC1 | Kurt | Ext 3σ | Jump | HIGH+EXT freq | Cluster | NN |
|---|---|---|---|---|---|---|---|---|---|---|
| AUDCAD | forex | 0.063 | 0.33 | 0.97 | 5.6 | 0.010 | 0.002 | 0.12 | 1 | — |
| AUDCHF | forex | 0.078 | 0.41 | 0.98 | 7.9 | 0.008 | 0.002 | 0.16 | 1 | — |
| AUDJPY | forex | 0.094 | 0.36 | 0.98 | 4.7 | 0.011 | 0.007 | 0.17 | 1 | — |
| AUDNZD | forex | 0.042 | 0.31 | 0.97 | 2.1 | 0.013 | 0.005 | 0.13 | 1 | — |
| AUDUSD | forex | 0.090 | 0.35 | 0.98 | 4.5 | 0.013 | 0.004 | 0.11 | 1 | — |
| BTCUSD | crypto | 0.378 | 0.38 | 0.97 | 4.9 | 0.017 | 0.014 | 0.15 | 1 | USDJPY |
| CADCHF | forex | 0.063 | 0.36 | 0.97 | 7.4 | 0.011 | 0.008 | 0.16 | 1 | — |
| CADJPY | forex | 0.085 | 0.34 | 0.98 | 2.7 | 0.016 | 0.007 | 0.13 | 1 | — |
| CHFJPY | forex | 0.074 | 0.34 | 0.97 | 4.9 | 0.014 | 0.007 | 0.12 | 1 | — |
| EURAUD | forex | 0.065 | 0.38 | 0.98 | 7.4 | 0.008 | 0.005 | 0.10 | 1 | — |
| EURCAD | forex | 0.053 | 0.32 | 0.98 | 2.2 | 0.014 | 0.008 | 0.13 | 1 | — |
| EURCHF | forex | 0.045 | 0.36 | 0.98 | 3.4 | 0.014 | 0.005 | 0.10 | 1 | — |
| EURGBP | forex | 0.043 | 0.44 | 0.98 | 5.8 | 0.016 | 0.008 | 0.09 | 1 | — |
| EURJPY | forex | 0.077 | 0.35 | 0.97 | 3.8 | 0.013 | 0.012 | 0.13 | 1 | — |
| EURNZD | forex | 0.065 | 0.33 | 0.98 | 3.2 | 0.008 | 0.004 | 0.09 | 1 | — |
| EURUSD | forex | 0.065 | 0.36 | 0.98 | 3.1 | 0.015 | 0.006 | 0.15 | 1 | USDCAD |
| GBPAUD | forex | 0.064 | 0.37 | 0.98 | 5.8 | 0.009 | 0.004 | 0.12 | 1 | — |
| GBPCAD | forex | 0.058 | 0.40 | 0.98 | 7.8 | 0.011 | 0.004 | 0.09 | 1 | — |
| GBPCHF | forex | 0.060 | 0.46 | 0.98 | 7.9 | 0.014 | 0.007 | 0.10 | 1 | — |
| GBPJPY | forex | 0.082 | 0.37 | 0.98 | 4.1 | 0.012 | 0.012 | 0.13 | 1 | — |
| GBPNZD | forex | 0.063 | 0.36 | 0.98 | 3.5 | 0.008 | 0.006 | 0.12 | 1 | — |
| GBPUSD | forex | 0.072 | 0.42 | 0.98 | 5.5 | 0.014 | 0.004 | 0.10 | 1 | — |
| NZDCAD | forex | 0.067 | 0.27 | 0.97 | 1.7 | 0.010 | 0.003 | 0.11 | 1 | — |
| NZDCHF | forex | 0.075 | 0.37 | 0.98 | 4.0 | 0.010 | 0.004 | 0.16 | 1 | — |
| NZDJPY | forex | 0.091 | 0.33 | 0.97 | 3.5 | 0.011 | 0.008 | 0.19 | 1 | — |
| NZDUSD | forex | 0.091 | 0.31 | 0.97 | 2.5 | 0.011 | 0.005 | 0.10 | 1 | — |
| US30 | indices | 0.122 | 0.49 | 0.98 | 13.1 | 0.016 | 0.007 | 0.18 | 1 | USTEC |
| USDCAD | forex | 0.051 | 0.36 | 0.98 | 3.2 | 0.014 | 0.005 | 0.11 | 1 | — |
| USDCHF | forex | 0.072 | 0.35 | 0.97 | 6.6 | 0.011 | 0.007 | 0.15 | 1 | — |
| USDJPY | forex | 0.088 | 0.36 | 0.98 | 3.5 | 0.017 | 0.012 | 0.14 | 1 | — |
| USTEC | indices | 0.186 | 0.47 | 0.98 | 9.8 | 0.016 | 0.003 | 0.20 | 1 | US30 |
| XAGUSD | metals | 0.318 | 0.69 | 0.98 | 43.1 | 0.012 | 0.009 | 0.37 | 2 | XAUUSD |
| XAUUSD | metals | 0.156 | 0.53 | 0.99 | 10.3 | 0.017 | 0.011 | 0.44 | 2 | US30 |
| XNGUSD | energy | 0.498 | 0.31 | 0.98 | 1.9 | 0.006 | 0.001 | 0.13 | 1 | EURNZD |

Asset-specific digests (BTC extreme/jump profile, XNG vol-of-vol, XAU/XAG pair correlations 0.85/0.77, US30/USTEC 0.91/0.81, JPY family) in `taxonomy_results.json → asset_specific`.

## Appendix C — §52 trade-path table (medians, n ≥ 20 gate)

| Asset | n | Hold | ttf | tt-MAE | tt-MFE | uw-run | uw-frac | MAE | MAE/σ | MFE | MFE/σ | cross | eff | win |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AUDUSD | 167 | 6 | 1 | 3 | 4 | 2 | 0.40 | 0.0074 | 1.65 | 0.0080 | 1.63 | 1 | 0.44 | 0.515 |
| EURUSD | 167 | 6 | 1 | 3 | 4 | 2 | 0.40 | 0.0051 | 1.68 | 0.0058 | 1.98 | 0 | 0.45 | 0.509 |
| GBPUSD | 152 | 6 | 1 | 3 | 4 | 2 | 0.40 | 0.0070 | 1.90 | 0.0066 | 1.85 | 0 | 0.45 | 0.500 |
| NZDUSD | 151 | 6 | 1 | 3 | 3 | 2 | 0.60 | 0.0093 | 2.00 | 0.0074 | 1.55 | 1 | 0.43 | 0.483 |
| USDCAD | 167 | 6 | 1 | 3 | 3 | 3 | 0.60 | 0.0057 | 1.89 | 0.0047 | 1.63 | 1 | 0.42 | 0.467 |
| USDCHF | 173 | 6 | 1 | 3 | 4 | 2 | 0.60 | 0.0060 | 1.56 | 0.0058 | 1.55 | 0 | 0.44 | 0.497 |
| USDJPY | 167 | 6 | 1 | 3 | 4 | 2 | 0.40 | 0.0062 | 1.73 | 0.0064 | 1.82 | 1 | 0.41 | 0.539 |
| XAUUSD | 167 | 6 | 1 | 3 | 4 | 1 | 0.40 | 0.0105 | 1.49 | 0.0151 | 2.32 | 0 | 0.45 | 0.611 |

No-profit rates: AUD 25.1% · EUR 25.7% · GBP 23.7% · NZD 29.1% · CAD 29.3% · CHF 26.0% · JPY 20.4% · XAU 18.6%. P25/P75/P90/P95 per cell in JSON.

## Appendix D — §53 regime-conditional trade table (population, PIT percentile)

| Regime | n | med ttf | med uw-run | med tt-MFE | med MAE | med MFE | med x/bar | med eff | uw-frac | win | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| LOW | 606 | 1 | 2 | 4 | 0.0062 | 0.0065 | 0.000 | 0.452 | 0.40 | 0.538 | reported |
| NORMAL | 631 | 1 | 2 | 4 | 0.0073 | 0.0069 | 0.167 | 0.433 | 0.60 | 0.487 | reported |
| HIGH | 74 | 1 | 2 | 4 | 0.0080 | 0.0094 | 0.129 | 0.412 | 0.40 | 0.581 | reported |
| EXTREME | 0 | — | — | — | — | — | — | — | — | — | **INSUFFICIENT DATA** |

Win-rate ordering (HIGH > LOW > NORMAL) has no monotone gradient and no Holm-tested claim attaches to it (descriptive cell). σ-normalized MAE/MFE medians are absent from this aggregate cell (stored per-asset×regime grid only). Full per-metric medians: `trade_path_results.json → regime_conditional`; per-asset × regime grid: `path_tables_partial.per_asset_regime` (per-asset HIGH/EXTREME cells largely INSUFFICIENT DATA at n < 20).

## Appendix E — §54 volatility × trade-path matrix

```
                        Trade-path resolution
                    fast(≤1)   moderate(2-3)   slow(≥4)   no_profit
LOW entry vol        0.523        0.175        0.063      0.239     n=606
NORMAL               0.512        0.179        0.051      0.258     n=631
HIGH                 0.514        0.203        0.068      0.216     n=74
EXTREME                —            —            —          —       INSUFFICIENT DATA
```

Descriptive only. Rows are flat: entry volatility regime does not sort resolution speed.

## Appendix F — §64 final questions

| Question | Answer |
|---|---|
| **Volatility** — distinct states in the current universe? | Two primary archetypes at k=2 (metals vs rest) plus continuous level spread AUDNZD 4.2% → XNGUSD 49.8% mean RV; regime occupancy differs markedly (XAU HIGH+EXT 44% vs EURGBP 9%). |
| **Stability** — stable through time? | **UNSTABLE** membership across thirds (ARI_min −0.04); method-robust within the full window; LOO-stable. |
| **Trade path** — does regime affect resolution speed? | **No detectable effect.** Medians identical across LOW/NORMAL/HIGH; speed shares flat; EXTREME has no data. |
| **Low-vol hypothesis** — longer underwater, more oscillation, slower resolution? | **NOT SUPPORTED** (combined). H1–H4 INCONCLUSIVE with wrong-signed pooled ρ; 9/12 falsifications fail. |
| **Normalization** — effect remains after σ-normalization? | Duration/oscillation effects do not exist to begin with (H5 NOT SUPPORTED for sign persistence; underwater_fraction ρ ≈ 0). σ-normalized *excursion* is larger at low entry percentile — a scale fact, not the claimed path behavior. |
| **Asset specificity** — vol vs particular assets? | Neither: within-asset tests (32, Holm) give 0 SUPPORTED; the effect is not cross-sectional nor within-asset. |
| **Incremental universe** — USOIL or Copper new archetype? | USOIL **STRUCTURALLY REDUNDANT**; Copper **STRUCTURALLY DISTINCT** (volatility space; trade-path novelty INSUFFICIENT DATA — not traded). |
| **Production boundary** | Descriptive: everything in §7–§18, Appendices A–E. Robust negative finding: low-vol path claim NOT SUPPORTED (may inform deprioritization only). Requires separate registered experiments: any stop/hold/sizing/exclusion/threshold change — **none authorized or implied.** |

---

*End of report. Generated artifacts are byte-pinned in `reproducibility.json`; regenerate with `python -m research.volatility.runner`.*
