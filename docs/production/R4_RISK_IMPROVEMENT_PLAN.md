# R4 Risk Improvement Plan

Scoring: `benefit × evidence_strength ÷ (complexity × new_risk)`; full table in `reports/r4_economics_audit/improvement_ranking.json`.

---

## A. IMPLEMENT NOW — safety/deployment integrity (not backtest optimization)

| # | Item | Score | Basis |
|---|---|---|---|
| 1 | **Deployed-build pinning** — audited commit, startup + per-cycle fingerprint proof, build-id in every audit record | 25.0 | P0-4: live process ≠ HEAD |
| 2 | **Foreign-position quarantine + PQ attribution repair + fresh T0** | 12.5 | P0-3: ~$789K magic=0 notional; PQ asserts Manual trades: 0 |
| 3 | **Midnight baseline guard** (DailyLossTracker zero-equity poisoning) | 20.0 | P1-2 observed |
| 4 | **Per-position loss gate: implement or remove the declaration** | 7.5 | P1-1 |
| 5 | **Alert dedup + audited SKIPs + absolute audit paths** | 7.5 | 1:1,506 amplification; silent outage SKIPs |
| 6 | **Single canonical regime definition** across research/live/monitor | 3.75 | three universes (15/31/6 symbols) |
| 7 | **Catastrophic broker-side disaster SL ≥ 2×ATR (or watchdog auto-flatten w/ retry)** | 5.00 | containment proven: MaxDD −12.3%→−6.7% at Sharpe drag ≤0.05 (F2 trials); judged on containment per preregistered criteria — NOT an economic exit |
| 8 | **Bridge failover / acting watchdog + proven external escalation** | 3.33 | 9.5h blind window; alert-only monitor |

## B. PREREGISTERED RESEARCH (no production deployment without OOS confirmation)

1. **Loser time-stop (exit if <0 after 10 bars)** — sole control-beater (+0.068 Sharpe, −45% MaxDD, false-stop 22.8%) but not Bonferroni-significant → confirm on out-of-sample window before any consideration.
2. **Cadence correction (weekly-declared vs daily-operational)** — weekly reconstruction dominates daily on every metric (+2.17% vs +0.74%/trade); resolve via preregistered cadence test.
3. **Entry filter: rank ≤ N strongest only** — rank-1/2 entries carry all measured edge (+3.6%/trade vs −0.2%); post-hoc subgroup ⇒ requires full purged-WF + multiple-testing pipeline.
4. Volatility-targeted portfolio overlay; correlation-aware sizing / CVaR limits.
5. Spread/slippage entry filters — first build fill-telemetry (request-vs-deal price persistence), then evaluate.
6. Weekend gap reduction policy; adaptive rebalance cadence; second-broker failover.

## C. DO NOT IMPLEMENT (evidence of harm)

1. **Take-profits at any level** — all 7 trials ΔSharpe −0.34…−0.63; destroys the convexity that constitutes the edge.
2. **Tight fixed stops (<1%) and ALL trailing variants** — Sharpe destruction up to −1.41.
3. **Winner time-caps (60d/120d)** — false-stop rates 43–58%; 40d+ bucket holds 84% of positive P&L.
4. **Regime-OFF flattening as economic policy** — ΔSharpe −0.71; riding frozen periods through recovery is superior. (May be revisited strictly as a catastrophic fallback if broker-side SL cannot be engineered.)

## D. Implementation rules

- Every production candidate: separate implementation + unit/integration/failure-injection tests + regression suite + new fingerprint + explicit qualification run. Frozen R4 remains control until a variant passes the ladder.
- The catastrophic layer (#7) must be safety-tested offline first and must never become an active profit-management signal.

## E. Priority order

`#1 → #2 → #3 → #4/#5 (parallel) → #6 → #7 → #8`, then resume qualification clock; research items B run concurrently offline.
