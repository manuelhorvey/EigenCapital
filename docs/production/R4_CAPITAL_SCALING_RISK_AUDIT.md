# R4 Capital Scaling & Risk Audit

---

## 1. Portfolio risk at $5K

| Quantity | Value | Source |
|---|---|---|
| Gross exposure (active days, simulated) | avg ~1.05× equity, max 1.96× | `portfolio_curve_daily.csv` |
| Position cap | 8 × $1,500 = $12K gross design (≈240%) | config |
| Min-lot flooring at $5K | All bot fills at 0.01 lots; intended \|w\|×equity often < min-lot notional → realized sizes ≠ targets | live deals |
| Correlated-shock example | −5% uniform ≈ −$600 (−12% eq); −10% crash approaches margin relevance at 2000:1 | stress grid |
| **Live contamination** | 8 foreign magic=0 positions ≈ **$789K notional (~117–146× eq)** dominated the real account's P&L path ($4,886↔$6,753 observed) | broker exports |

**Answer to the core question:** eight *compliant* $1,500 positions produce bounded, survivable portfolio risk (worst modeled DD −12.3%). The actual $5K account did NOT contain eight compliant R4 positions alone — the observed risk came from foreign, unprotected, over-leveraged books that EigenCapital's gates could not touch.

## 2. Capital tiers — constraint mapping (not linear extrapolation)

Min-lot notionals (config): AUDCHF $574 … GBPUSD $1,363; BTCUSD ~$792.

| Tier | Symbols tradable at typical \|w\|≈0.05 target | Untradeable even at ±0.20 clip | Verdict |
|---|---|---|---|
| $5K | 2–4/16 | 0/16 | **CONDITIONAL** — only tier with any live evidence; evidence contaminated (P0-3) and safety gaps open (P0-1) |
| $10K | 8/16 | 0/16 | NOT JUSTIFIED YET |
| $25K | 16/16 | 0/16 | NOT JUSTIFIED YET |
| $50K | 16/16 | 0/16 | NOT JUSTIFIED YET (flooring pressure easing) |
| $100K | 16/16 | 0/16 | NOT JUSTIFIED YET (single-order lot caps begin to bind; multi-fill unproven) |
| $250K–$1M | 16/16 | 0/16 | NOT JUSTIFIED YET ($500K+: RiskPolicy 25% concentration conflicts with 30% position design → redesign, not scaling) |

Liquidity/market impact: negligible below ~$10M gross for these instruments; strategy capacity is gated by *evidence*, not market depth.

## 3. Profitability dynamics (statistical scenarios — NOT guarantees)

Block-bootstrap of control daily net returns (20-day blocks, 2000 draws):

| Scenario | Ann. return | Ann. vol | Sharpe | P(losing month) | Years to double | P(−20% DD in 1y, normal approx) |
|---|---|---|---|---|---|---|
| Conservative (P10) | +0.95% | 4.7% | 0.20 | 35% | ~74 | ~1e-6 |
| Baseline (P50) | +2.95% | 4.7% | 0.63 | 35% | ~24 | ~1e-6 |
| Optimistic (P90) | +5.15% | 4.7% | 1.09 | 35% | ~14 | ~1e-6 |

- Cost drag: gross→net ≈ **−2.59%/yr** on daily cadence (weekly cadence reduces it).
- The normal-approx drawdown probability ignores gap/fat-tail risk and assumes controls work; treat as a lower bound.
- Compounding is intentionally disabled during qualification by the max_equity=$5,100 sizing cap.
- At $5K with min-lot flooring, realized returns will deviate from weight-space scenarios (flooring both oversizes weak signals and blocks small ones).

## 4. Long-duration survival

Platform tests at HEAD PASS (endurance/chaos/DR suites, 44 freeze tests), **but the deployed campaign binary predates HEAD** (P0-4): DisconnectRecovery never engaged during the observed 9.5h outage; monitor was alert-only; single bridge host is an unmitigated SPOF. Months-scale operation is **UNPROVEN IN DEPLOYMENT** until build-pinning + acting watchdog conditions are met (`long_duration_survival.json`).

## 5. Verdicts

### PORTFOLIO RISK (design intent): **YELLOW** — bounded by construction, but only if positions are actually compliant and a reduction path exists.
### LIVE ACCOUNT RISK (reality): **RED** — foreign-book leverage up to ~146× with zero protection.
### MAX CURRENTLY JUSTIFIED TIER: **$5K, CONDITIONAL**
### CAPITAL SCALING: evidence-gated promotion only; every tier above $5K NOT JUSTIFIED YET.

*Artifacts: `capital_scaling.json`, `profitability_scenarios.json`, `long_duration_survival.json`, `live_vs_paper_comparison.json`, `PRELIMINARY_SAFETY_TRIAGE.json`.*
