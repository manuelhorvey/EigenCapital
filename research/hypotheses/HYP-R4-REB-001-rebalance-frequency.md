# HYP-R4-REB-001: R4 Rebalancing Frequency — When Should the Frozen Target Be Acted Upon?

**Experiment:** EXP-000002 · **Trial group:** R4-REB-MATRIX-V1 · **Status:** PRE_REGISTERED

## Motivation

The frozen R4 signal computes a daily target portfolio, but the *intervention
clock* — how often the live loop actually acts on that target — has never been
studied. The loop wakes hourly and trades whenever the order plan is non-empty.
On a ~$5k account, min-lot granularity plus per-trade costs mean unnecessary
interventions may destroy economically useful signal capture. This experiment
ablates ONLY the intervention clock: the signal, universe, sizing, risk gates,
and execution path are untouched.

## Pre-Registered Candidate Matrix (8 trials, one family)

| Trial ID | Policy | Semantics |
|---|---|---|
| R4-REB-CANONICAL | CANONICAL | frozen baseline: act whenever orders exist |
| R4-REB-DAILY | DAILY | ≤ 1 intervention per UTC calendar day |
| R4-REB-WEEKLY | WEEKLY | deterministic weekly anchor (Mon 00:00 UTC default) |
| R4-REB-T005 | THRESHOLD | no-trade band 0.5% |
| R4-REB-T010 | THRESHOLD | no-trade band 1.0% |
| R4-REB-T020 | THRESHOLD | no-trade band 2.0% |
| R4-REB-T050 | THRESHOLD | no-trade band 5.0% |
| R4-REB-HYBRID-T010 | HYBRID | 1.0% band + canonical event overrides |

The grid is pre-registered. No threshold search outside this grid may be
presented as evidence; any extension requires a new trial group.

## Falsifiable Hypotheses (not assumptions)

### H1 — Turnover reduction
Less frequent intervention reduces turnover and transaction costs.
**Falsified if:** no policy achieves materially lower turnover than CANONICAL
with comparable tracking error.

### H2 — Capture vs. frequency
Daily intervention captures target changes faster.
**Falsified if:** CANONICAL/DAILY tracking error is not lower than
weekly/threshold tracking error.

### H3 — Implementation efficiency
Threshold-based intervention improves net implementation efficiency
(net return per unit turnover).
**Falsified if:** no threshold candidate improves return_per_turnover over
CANONICAL at base cost.

### H4 — Risk drift
Threshold-based intervention does not materially increase risk drift
(max drawdown, tracking error, exposure distortion).
**Falsified if:** a threshold candidate's max drawdown or tracking error
degrades beyond pre-specified tolerance vs CANONICAL (Δ MaxDD > 2pp).

### H5 — Hybrid trade-off
Hybrid intervention provides a better cost/risk trade-off than fixed cadence.
**Falsified if:** HYBRID is dominated by (WEEKLY or a THRESHOLD candidate) on
both net Sharpe and max drawdown.

## Method

- SAME frozen R4 signal for every policy (parity-verified offline
  reconstruction; Section 14 ablation, identical targets per date).
- No look-ahead: decisions at T use bars ≤ T; trades price at T's close.
- Uniform cost model: transaction_cost_bps + slippage_bps per unit of
  one-sided turnover in weight space; identical for every policy.
- Cost ladder: base / ×1.25 / ×1.5 / ×2 applied uniformly.
- Min-lot floor mirrored from live sizing (diagnostic only).
- Metrics: net Sharpe, net return, max drawdown, turnover (total +
  annualized), cost drag, cost/gross, return per unit turnover, tracking
  error (mean/max), holding period, min-lot distortion, event counts.

## Falsification Criteria (experiment level)

**REJECT the family (no promotion candidate exists) if any of:**

1. No policy reduces turnover materially without unacceptable risk drift.
2. Any "win" disappears at base × 1.5 costs.
3. The best result is isolated to a single regime or a short sub-period.
4. Improvement depends on one razor-thin threshold (not robust across the grid).
5. Execution-fidelity diagnostics (min-lot distortion, tracking error) show
   no consistent improvement pattern.

## Non-Promotion Clause

No candidate becomes a production policy from this experiment alone.
Promotion requires the Section-27 gates (statistical, economic, turnover,
risk, stability, sensitivity, execution, operational) plus restart/idempotency
test certification, evaluated on out-of-sample evidence gathered after this
pre-registration.

## Registration

- **Experiment ID:** EXP-000002
- **Registered:** 2026-09-16 (registry: research/experiments/registry/EXP-000002.json)
- **Status:** PRE_REGISTERED (test parameters frozen)
