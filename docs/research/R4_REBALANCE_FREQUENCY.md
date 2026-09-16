# R4 Rebalancing Frequency — When Should the Frozen Target Be Acted Upon?

**Experiment:** EXP-000002 · **Hypothesis:** HYP-R4-REB-001 · **Trial group:** R4-REB-MATRIX-V1
**Status:** PRE-REGISTERED, FULL-SAMPLE BASELINE COMPLETE — **no production change made or recommended yet**
**Signal lineage:** frozen R4 (EXP-000001), reconstructed by the C1 parity-verified path
`scripts/r4_shadow_portfolio.py::replicate_signal` + `build_universe` (no second signal implementation).

---

## 1. Objective

The frozen R4 signal computes a daily target portfolio. The live loop wakes hourly and,
today, trades **every** cycle whose order plan is non-empty (`CANONICAL` behavior). The
intervention clock — how often the portfolio actually acts on an already-computed target —
has never been studied. This experiment ablates **only** the intervention clock:

```
FROZEN R4 signal  →  SAME target portfolio at every decision date  →  ONLY the policy differs
```

Everything upstream (signal, lookbacks, ranking, regime, vol-scaling, clips, universe) and
everything downstream (risk gates, execution safety, reconciliation, min-lot handling) is
byte-identical across arms. The question answered:

> For the frozen R4 signal, how frequently should the portfolio intervene to maximize net
> economic efficiency after transaction costs, while keeping risk/exposure drift acceptable?

## 2. Hypotheses (falsifiable, pre-registered)

| # | Hypothesis | Verdict (full-sample baseline) |
|---|------------|-------------------------------|
| H1 | Less frequent intervention reduces turnover and transaction costs. | **Supported for WEEKLY only** (−56% turnover, −56% cost). **Rejected for per-symbol threshold bands.** |
| H2 | Daily intervention captures target changes faster (higher gross). | **Supported** — daily arms have the highest gross return (+1.218 vs +1.095 weekly). |
| H3 | Threshold-based intervention improves net implementation efficiency. | **Rejected.** Every band width ≥ T005 has *higher* turnover and *lower* net return than CANONICAL. |
| H4 | Threshold-based intervention does not materially increase risk drift. | **Mixed.** Drawdown improves slightly, but weight tracking error degrades by construction; the band under-tracks targets (realized vol 12.3% vs 17.0% = under-deployment, not risk control). |
| H5 | Hybrid (band + canonical events) beats both fixed cadences. | **Not yet decidable.** In offline replay hybrid degenerates to THRESHOLD (no live events exist); ≡ T010. Live shadow phase required. |

## 3. Policies and exact semantics

All policies live in `src/eigencapital/live/rebalance_policy.py` and share one contract:

```
should_rebalance(current_weights, target_weights, signal_timestamp, now, events) → RebalanceDecision
  action: TRADE | HOLD        reason: NEW_SIGNAL | WEIGHT_DRIFT | EXIT_SIGNAL | ...
  tradable_symbols / banded_symbols, max_weight_deviation, gross_turnover_if_traded
```

| Policy | ID | Semantics |
|--------|----|-----------|
| Canonical (production default) | `R4-REB-CANONICAL` | Never vetoes, never filters — the loop's pre-research behavior exactly. Selected by default (no env var). |
| Daily | `R4-REB-DAILY` | At most one intervention per UTC calendar day; hourly wake-ups still run monitoring/risk. |
| Weekly | `R4-REB-WEEKLY` | One intervention per ISO week, anchored Monday 00:00 UTC (window `[Mon 00:00, next Mon 00:00)`), configurable weekday/hour. |
| Threshold | `R4-REB-T005/T010/T020/T050` | Per-symbol no-trade band; only *adjustments* are gated. Discrete events always trade: new entry, full exit, reversal. |
| Hybrid | `R4-REB-HYBRID-T010` | Threshold band + immediate trade on canonical events (regime transition, risk-mandated reduction, reconciliation correction). No new event types invented. |

**Exact threshold semantics** (tested, boundary-explicit):

```
deviation > threshold  → trade      deviation ≤ threshold → hold (boundary belongs to the no-trade side)
target ≠ 0, current = 0 → TRADE (entry — never banded)
target = 0, current ≠ 0 → TRADE (exit  — never banded)
sign flip (both ≠ 0)    → TRADE (reversal)
```

**Turnover convention (single formula, no competing definition):**
`Σ |Δw|` over symbols **actually traded** (one-sided, weight space). Banded/carried symbols
place no order and pay nothing — deferred band drift is *never* charged to a later cycle.
Every unit of turnover pays `cost_bps` once (project's 10 bps/side convention, C7), so all
arms are compared under an identical cost model (Section 11 requirement).

**Selection & persistence:** policy chosen by `R4_REBALANCE_POLICY` env var (`CANONICAL`
default) — **deliberately not** in `EigenCapitalConfig`, because any config-field addition
changes the frozen config fingerprint and would fail-closed block live trading. State lives
in its own `rebalance_policy_state.json` (`runtime_state.json` never touched). Research
decisions append to `reports/r4_loop/rebalance_policy_decisions.jsonl` — canonical R4
ledgers are never written by the policy layer.

## 4. Results — full sample 2020-01-02 → 2026-08-24 (2427 daily decisions, 42 symbols, 15 bps)

### 4.1 Primary table (Section 30)

| Policy | Rebalances | Orders | Turnover | Gross Ret | Cost Drag | Net Ret | Net Sharpe | Max DD | Track Err (mean) | Ret / Turnover |
|--------|-----------:|-------:|---------:|----------:|----------:|--------:|-----------:|-------:|-----------------:|---------------:|
| CANONICAL (= live today) | 1391 | 29,422 | 213.3 | +1.2179 | −0.3200 | +0.8979 | 0.550 | −27.1% | 2.60% | 0.42% |
| DAILY | 1391 | 29,422 | 213.3 | +1.2179 | −0.3200 | +0.8979 | 0.550 | −27.1% | 2.60% | 0.42% |
| WEEKLY | **229** | **5,181** | **94.2** | +1.0953 | **−0.1413** | **+0.9541** | **0.588** | **−25.8%** | 3.11% | **1.01%** |
| T0.5% | 1304 | 9,081 | 326.1 | +0.8759 | −0.4892 | +0.3868 | 0.325 | −23.7% | 0.07% | 0.12% |
| T1% | 1198 | 6,660 | 312.7 | +0.8733 | −0.4690 | +0.4044 | 0.340 | −23.6% | 0.14% | 0.13% |
| T2% | 1119 | 5,583 | 301.2 | +0.8920 | −0.4518 | +0.4401 | 0.371 | −23.4% | 0.26% | 0.15% |
| T5% | 1042 | 5,089 | 290.7 | +0.9083 | −0.4360 | +0.4724 | 0.398 | −23.4% | 0.45% | 0.16% |
| HYBRID-T1% | 1198 | 6,660 | 312.7 | +0.8733 | −0.4690 | +0.4044 | 0.340 | −23.6% | 0.14% | 0.13% |

- **DAILY ≡ CANONICAL is a grid artifact**: on a D1 daily grid there is ≤1 candidate per
  day, so the cadence guards never bind. They differ only on the live hourly loop, where
  DAILY caps intra-day re-trades.
- **HYBRID ≡ T010 is expected offline**: replay contains no live risk/regime/reconciliation
  events, so the event layer is inert. Their difference can only be measured in shadow on
  the live loop.

### 4.2 Risk / exposure table

| Policy | Realized Vol (ann.) | Max Drawdown | Weight Track Err (mean) | Max Track Err |
|--------|--------------------:|-------------:|------------------------:|--------------:|
| CANONICAL | 17.0% | −27.1% | 2.60% | 20.0% (clip ceiling) |
| WEEKLY | 16.9% | −25.8% | 3.11% | 20.0% |
| T0.5%–T5% | 12.3–12.4% | −23.4…−23.7% | 0.07–0.45% | varies |

Threshold policies' low realized vol is **not** risk control — it is under-deployment: the
band stops them from tracking targets, so they hold less risk *and* capture much less
return (gross 0.87 vs 1.22). Weekly's realized vol and drawdown are statistically
indistinguishable from CANONICAL.

### 4.3 Cost sensitivity ladder (Section 20; net Sharpe at ×1 / ×1.25 / ×1.5 / ×2 of 15 bps)

| Policy | ×1.0 | ×1.25 | ×1.5 | ×2.0 |
|--------|-----:|------:|-----:|-----:|
| CANONICAL | 0.550 | 0.501 | 0.451 | 0.353 |
| **WEEKLY** | **0.588** | **0.566** | **0.544** | **0.500** |
| T0.5% | 0.325 | 0.222 | 0.119 | −0.086 |
| T1% | 0.340 | 0.241 | 0.143 | −0.054 |
| T2% | 0.371 | 0.275 | 0.180 | −0.010 |
| T5% | 0.398 | 0.306 | 0.214 | 0.030 |

Weekly dominates CANONICAL at every cost level and degrades the slowest. Threshold bands go
net-negative at 2× costs — they fail the "must not depend on unrealistically cheap
execution" test outright.

### 4.4 Min-lot distortion sensitivity (Section 21; `--min-lot-weight 0.05` ≈ $5k-account granularity)

| Policy | Net Sharpe (base) | Net Sharpe (5% floor) | Min-lot distortion |
|--------|------------------:|----------------------:|-------------------:|
| CANONICAL | 0.550 | 0.535 | 1.07% |
| WEEKLY | 0.588 | 0.586 | 1.07% |
| T1% | 0.340 | 0.290 | 1.12% |

Weekly is robust to floor distortion; CANONICAL degrades. No policy "solves" min-lot
distortion (and none was allowed to — Section 21) — this knob only stress-tests cadence
choices against execution granularity.

## 5. Key finding: why per-symbol bands *increase* turnover

R4's daily target changes are tiny (median |Δw| per symbol ≈ 0.2–0.7pp) and mean-reverting
around a slowly-moving target. A band suppresses a 0.4pp adjustment today; tomorrow the
deviation is 0.9pp and still under a 1% band; the day after it crosses and the policy pays
the **full accumulated drift in one order**. The band converts many small trades into
fewer, larger trades with *more* total notional. This is the band-edge whipsaw: for
mean-reverting micro-adjustments, threshold bands are turnover-amplifying, not
turnover-reducing. The regime is different for slow, trending target changes (the classic
no-trade-band use case) — R4's weight stream does not have that shape.

Weekly works because it batches an entire week of target revisions into one decisive
trade set (229 interventions, 5,181 orders), cutting both churn and cost drag, while the
signal's 12-1 momentum lookback makes weekly action nearly information-lossless.

## 6. Gate assessment (Section 27) — WEEKLY, the only surviving candidate

| Gate | Status | Evidence |
|------|--------|----------|
| 1 Statistical (no degradation vs baseline) | ⏳ pending | Requires walk-forward split (framework supports `--start/--end`); full-sample baseline is not sufficient. |
| 2 Economic (survives realistic costs) | ✅ pass (full sample) | Higher net return and Sharpe at every ladder multiplier. |
| 3 Turnover (meaningful reduction) | ✅ pass | −56% turnover, −82% orders, 2.4× return-per-turnover. |
| 4 Risk (no unacceptable drift) | ✅ pass (full sample) | Max DD −25.8% vs −27.1%; realized vol 16.9% vs 17.0%. |
| 5 Stability (not one regime/period) | ⏳ pending | Per-regime breakdown (Section 19) not yet implemented. |
| 6 Sensitivity (not razor-thin) | ✅ pass | Weekly has **no tuned parameter** (weekday/hour are operational choices); min-lot stress robust. |
| 7 Execution | ⏳ pending | Requires live shadow (execution failures, ambiguous outcomes, partial fills). |
| 8 Operational | ✅ pass | Restart/idempotency/boundary unit tests (45 policy + 17 replay + 10 integration) all green. |

**Recommendation: NO promotion.** WEEKLY proceeds to the mandatory next stages only:
(1) walk-forward validation, (2) regime breakdown, (3) live shadow comparison per
Section 28. Threshold/hybrid arms are **rejected at Gate 2** on this baseline.

## 7. Shadow-first live behavior (already implemented)

With the research module installed, the live loop (default) is unchanged. Setting e.g.
`R4_REBALANCE_POLICY=WEEKLY` makes the loop gate its **own** order plan through the policy
after risk gates and before order-intent persistence/execution, and every cycle appends a
decision row (timestamp, signal date, cycle id, policy id/version, target hash, decision,
reason, weights, deviation, turnover-if-traded, estimated cost, risk state, regime) to
`reports/r4_loop/rebalance_policy_decisions.jsonl`. `CANONICAL` (default) writes the same
evidence trail while never filtering anything — pure observation.

## 8. Reproduction

```bash
# pre-register (idempotent) — registers 8 trial configs under trial group R4-REB-MATRIX-V1
python3 scripts/r4_rebalance_research.py --register-only

# full-sample baseline
python3 scripts/r4_rebalance_research.py --out reports/r4_rebalance_research

# min-lot sensitivity (Section 21)
python3 scripts/r4_rebalance_research.py --min-lot-weight 0.05 --out reports/r4_rebalance_research_mlw005

# walk-forward windows (Gate 1 / Gate 5 support)
python3 scripts/r4_rebalance_research.py --start 2020-01-02 --end 2023-06-30 --out reports/wf_a
python3 scripts/r4_rebalance_research.py --start 2023-07-01 --end 2026-08-24 --out reports/wf_b
```

Artifacts: `research/experiments/registry/EXP-000002.json`,
`research/hypotheses/HYP-R4-REB-001-rebalance-frequency.md`,
`reports/r4_rebalance_research/rebalance_report_*.json` (primary table, risk table, cost
ladder, provenance, git head).

## 9. Limitations (explicit)

1. **Weight-space replay.** Positions are signed weights; contract sizes, spreads by
   symbol, FX conversion and lot rounding are approximated by a uniform bps cost and a
   symmetric min-lot floor. Relative comparisons between cadences are robust; absolute
   P&L is indicative only.
2. **Live risk gates not simulated** (regime gate, daily-loss gate, reconciliation,
   execution failures). Their interaction with cadence is exactly what the live shadow
   phase (Section 28) measures.
3. **No per-regime breakdown yet** (Section 19) — listed as follow-up work.
4. **Multiple-testing accounting**: 8 configs registered as 8 trials; the weekly-vs-
   canonical comparison should additionally be treated as selected-among-8 when Gate 1
   statistics run.

## 10. Frozen-R4 verification

`compute_r4_signal`, `generate_orders`, risk gates, execution stack and all config
dataclasses are untouched by this work. Verified three ways: (a) HEAD-only worktree passes
`tests/unit/test_t0_sizing.py` 25/25; (b) HEAD + research-only changes passes 96/96;
(c) shadow immutability guards (`test_r4_immutability.py`, `PROTECTED_R4_EVIDENCE_FILES`,
fingerprint verifier) pass in the full suite. The only loop-side edits are: module
docstring note, policy imports/registry, the gate block inside `run_cycle` (after the
ALIGNED return, before order-intent persistence), and an env-var echo in `main()`.
