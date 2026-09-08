# R4-S Diagnostics — Where Does the 48% Lost Edge Go?

**Date:** 2026-09-07 · **Selector version:** `r4s-shadow-selector-0.2.0`
**Window:** Jan 1 – Aug 24, 2026 (136 regime-on decision days)
**Method:** diagnostic only — no selector behavior changed, no hyperparameters
tuned. Evidence regenerated with `--size-breakdown`; analysis in
`scripts/r4_shadow_diagnostics.py` → `reports/r4_loop/shadow_diagnostics_summary.json`.

**Headline finding: the lost edge is NOT a correlation problem.**

> **87.3% of R4's discarded edge is charged to `currency_concentration` —
> the selector's hard currency cap, not the correlation penalty, is what
> removes R4's high-edge names.** Correlation/factor/weak-edge mechanisms
> together account for ~11% of the loss, and the soft correlation penalty
> accounts for ~0%.

That answers the phase-2 question with a much sharper hypothesis than the
aggregate −48% edge number implied: the shadow selector is currently
"throwing away alpha" **because strong signals share currencies**, not
because it is over-filtering correlation. The two lead to completely
different future research.

---

## D1 — Edge retained by selection size: no cliff, but the top-1 is thin

| Size | Days reaching N | Edge retained (avg) | Port vol (avg) | Max \|corr\| (avg) | Quality (avg) |
|---:|---:|---:|---:|---:|---:|
| 1 | 136 | 17.9% | 0.040 | 0.00 | 0.048 |
| 2 | 97 | 29.9% | 0.043 | 0.28 | 0.260 |
| 3 | 97 | 44.4% | 0.074 | 0.45 | 0.373 |
| 4 | 97 | 52.5% | 0.076 | 0.56 | 0.439 |
| 5 | 97 | 57.2% | 0.077 | 0.59 | 0.479 |
| 6 | 97 | 60.5% | 0.078 | 0.60 | 0.509 |
| 7 | 97 | 63.2% | 0.078 | 0.63 | 0.533 |
| 8 | 94 | 66.1% | 0.079 | 0.65 | 0.553 |

Reading:
- Edge is spread **roughly evenly** across R4's 20 names (~7–8% per position
  at the margin). There is no cliff — but the top-1 alone is thin (17.9%),
  and even N=8 captures only 66%.
- Portfolio vol barely falls after N=2 (0.043 → 0.079): additional names add
  nearly their full |w|·σ — the marginal names are **not diversifying** in
  variance terms, which is consistent with same-currency stacking (the thing
  the currency cap then rejects).
- On **39 of 136 days** the greedy chain stops at N=1: after the strongest
  signal, no second candidate was quality-positive. Avg shadow size 5.97 is
  a mix of 1-position days and deep days.

## D2 — Lost-edge attribution: the currency cap is the binding constraint

Total R4 edge 143.2 over the window; lost 69.3 (48.4%).

| Dominant reason for exclusion | Share of lost edge |
|---:|---:|
| **currency_concentration** | **87.32%** |
| factor_concentration | 10.60% |
| portfolio_capacity | 1.82% |
| weak_edge | 0.26% |
| high_correlation | **0.00%** |
| volatility_penalty | **0.00%** |

Edge substituted from outside R4's top-20: 0.07 (negligible — the shadow
picks almost entirely from R4's own set).

Interpretation: with the production universe full of AUD/NZD/CAD pairs, the
strongest momentum signals frequently share a currency. The hard cap
(max 80% of gross in one currency, enforced from 2 positions) admits only
1–2 names per currency and discards the rest — most of the "lost edge" is
those discarded same-currency names. The correlation penalty, by contrast,
is almost never the binding reason. This is the single most actionable
diagnostic result: **any future portfolio-construction hypothesis must first
be tested against the currency-redundancy mechanism, not correlation.**

## D3 — Risk/edge frontier: no stable Pareto improvement yet

| Size | Edge ret % | Port vol | Max \|corr\| | Realized gross | Net of 10bps/side | Avg R (rotation exits) |
|---:|---:|---:|---:|---:|---:|---:|
| R4 (20) | 100 | 0.086 | 0.891 | — | — | — |
| 1 | 17.9 | 0.040 | 0.00 | −622.4 | −642.2 | −2.14 (11 exits) |
| 2 | 29.9 | 0.043 | 0.28 | −210.5 | −223.4 | −1.77 (9) |
| 4 | 52.6 | 0.076 | 0.56 | −141.8 | −170.3 | +0.23 (36) |
| 6 | 60.6 | 0.078 | 0.60 | −2.0 | −46.7 | +0.14 (83) |
| 8 | 66.4 | 0.079 | 0.65 | −399.8 | −442.1 | +0.30 (94) |

Reading (with the honest caveat below):
- **Every size realized net-negative** in this window; costs (10 bps/side)
  add a meaningful but not dominant drag (−20 to −42).
- Rotation-exit R is **positive for N ≥ 4** (+0.14 to +0.30) but the
  realized totals are dominated by the **terminal close at the window end**
  (Aug 2026 was a loss month) — so the totals are fragile to the end point,
  another reason not to tune on them.
- There is **no monotone frontier**: N=6 is least-bad gross (−2.0), N=8
  worse (−400) despite more edge. More edge did not reliably buy less risk
  or better outcomes.

Caveat: per-N realized comes from a diagnostic tracker (same entry/exit
convention as the authoritative tracker; costs added per reconstruct C7);
the authoritative recommended-portfolio outcomes remain in
`shadow_portfolio_outcomes.jsonl`.

## D4 — Regime interaction: the losses concentrate in high-volatility states

| Bucket (vol_now/vol_median) | Days | Avg size | Edge ret % | Port vol | Realized PnL | Avg R | Hit |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| low_vol (≤ 0.821) | 46 | 5.57 | 53.3% | 0.055 | −33.1 | −0.003 | 15/36 |
| med_vol (0.821–0.913) | 45 | 6.11 | 51.7% | 0.075 | −8.0 | **+0.078** | 24/45 |
| high_vol (> 0.913) | 45 | 6.24 | 51.2% | 0.073 | **−296.4** | **−0.285** | 22/44 |

Reading: shadow performance is regime-dependent — near-breakeven in
low/medium vol, and **the entire loss is concentrated in high-volatility
regime days** (−296 of −337 total). Same behavior as the underlying R4
momentum positioning (risk-on longs in stress). The diversification layer
did not protect against regime loss — consistent with the correlation-model
instability we measure (avg cross-window Δcorr ≈ 0.14) and with the
established fact that correlations rise in stress. Diversification that only
works in calm regimes is not yet demonstrated value.

---

## What this means for the next research phase

1. **Reframe the hypothesis.** The interesting question is now:
   *"How much of the 87% currency-capped edge can be re-admitted without
   re-creating the redundant exposure the cap was designed to remove?"*
   Not correlation tuning.
2. **Next diagnostic to run (still not tuning):** a cap-sensitivity replay
   (e.g., currency cap 0.8 → 1.0 as a hypothesis test) to quantify how much
   edge the cap alone costs, and whether the re-admitted names change the
   realized result. This is a hypothesis test, not a parameter search, and
   should be preregistered like this one.
3. **Do not tune λ_risk / λ_corr / λ_ccy / λ_fac, windows, shrinkage, or
   size** against this single window — the terminal-close dominance and
   regime concentration make any such tuning overfit by construction.
4. **Watch the high-vol regime specifically** in live R4-S soak: if regime-
   concentrated losses persist, the correct experiment is about exposure
   control in stress, not about correlation.
5. **R4 remains the control group. Shadow stays shadow-only. No promotion,
   no behavior change.** This report adds diagnostics only.

---

### Artifacts

```text
scripts/r4_shadow_diagnostics.py                    the four diagnostics
reports/r4_loop/shadow_diagnostics_summary.json     machine-readable results
reports/r4_loop/shadow_portfolio_size_breakdown.jsonl  per-day per-N realized (gross/net)
reports/r4_loop/shadow_portfolio_decisions.jsonl    enriched: chain_by_n, marginal_components,
                                                    dominant_rejection, regime (136 records)
````configs/` unchanged. R4 evidence untouched. No commit.

### Operational finding (mid-session, 2026-09-07 23:53 UTC)

While regenerating evidence for this report, an external rotation moved the
entire `reports/r4_loop/` directory to the OS trash (a prior rotation
occurred 2026-09-06 12:16 UTC; the live `r4_rebalance_loop.py`/
`r4_monitor.py` processes were running and recreated the directory with
fresh runtime files within the same minute). The co-located shadow evidence
files were caught in the rotation and subsequently **regenerated cleanly**
(136 records, byte-deterministic across runs).

Action taken: shadow evidence was regenerated from the frozen signal (no
restore from trash, to avoid clobbering the live loop's fresh R4 runtime
files) and determinism was re-verified. Note for the soak phase: shadow
evidence co-located inside `reports/r4_loop/` can be lost on the next
rotation; the recorder already supports a dedicated out-dir via
`EIGENCAPITAL_SHADOW_OUT_DIR` (or `--out-dir`) if a rotation-proof location
is preferred.
