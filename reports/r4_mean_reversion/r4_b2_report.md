# R4-B2 — Mean Reversion / Stat-Arb 8-Pair Family (OBSERVED report)

**Experiment:** R4-B2 mean-reversion / stat-arb preregistered 8-pair family  
**Contract:** `docs/research/R4_MEAN_REVERSION.md (R4-B2 preregistration, frozen before code/data access)` — preregistration frozen BEFORE code and data access  
**Run:** 2026-09-17T22:54:56.283435+00:00 · deterministic (seed 42, n=1000)  
**Universe:** r4_local_v1_b2 — 8 pairs, economic rationale declared ex ante (see ledger)  
**OOS split:** exit bar index ≥ 765 (frozen R3 WF geometry)  
**Costs:** 60 bps per round trip (4 legs × 15 bps)

> **What this is:** a research-only mean-reversion/stat-arb family
> evaluated against its preregistered falsification arms and the
> pre-committed parking rule.
> **What this is NOT:** a statement about the frozen R4 production
> strategy, and not a promotion decision.

## Verdict: **PARKED**

> pre-committed parking rule FIRED: 5 total trades across the 8-pair family < 20. The mean-reversion family is PARKED on daily bars — no gate recalibration, no window changes, no universe expansion beyond this set, no re-attempt on this data class. Reopening requires a material data upgrade (intraday or order-flow data). The hypothesis remains unresolved-not-falsified on this data class..

## Pre-committed parking rule

- Threshold: < 20 total trades across the family → PARKED.
- Observed: **5 total trades** → **RULE FIRED.**

## Holm family (ONE preregistered family over the 8 pairs)

- R4-B2: 8-pair mean-reversion family, per-pair sign-flip permutation p-values
- n_tests = 0; any pair significant after Holm: **False** — only 0 pair(s) had ≥2 OOS trades — Holm family not applicable; missing evidence stays missing

## Falsification arms

- **F-B** (pooled OOS net P&L after full costs): -0.2114 over 4 OOS trades
- **F-C** (correlation with frozen-R4 replica < 0.7, diagnostic): rho = 0.024445562051502893 over 1863 overlap days

## Per-pair diagnostics

| Pair | bars | est. dates | active | trades (IS/OOS) | gate≥20 | raw p | net P&L | hit rate | cancelled | WF windows |
|---|---|---|---|---|---|---|---|---|---|---|
| AUDUSDm/NZDUSDm | 2076 | 87 | 0 | 0/0 | FAIL | n/a | 0.0000 | 0.000 | 0 | 4 |
| EURUSDm/GBPUSDm | 2076 | 87 | 3 | 0/1 | FAIL | n/a | -0.0039 | 0.000 | 0 | 4 |
| EURUSDm/USDCHFm | 2076 | 87 | 1 | 0/1 | FAIL | n/a | -0.0129 | 0.000 | 0 | 4 |
| USDCADm/USOILm | 2066 | 87 | 1 | 0/0 | FAIL | n/a | 0.0000 | 0.000 | 0 | 4 |
| XAUUSDm/XAGUSDm | 2066 | 87 | 1 | 0/0 | FAIL | n/a | 0.0000 | 0.000 | 1 | 4 |
| US30m/US500m | 2068 | 87 | 3 | 0/1 | FAIL | n/a | 0.0048 | 1.000 | 0 | 4 |
| USTECm/US500m | 2068 | 87 | 1 | 1/0 | FAIL | n/a | 0.0111 | 1.000 | 0 | 4 |
| BTCUSDm/ETHUSDm | 2428 | 104 | 1 | 0/1 | FAIL | n/a | -0.1995 | 0.000 | 0 | 5 |

Gate failures by type (across estimation dates):

- AUDUSDm/NZDUSDm: {'adf': 87, 'coint': 78, 'half_life': 6} (active 0/87)
- EURUSDm/GBPUSDm: {'adf': 78, 'coint': 76, 'half_life': 0} (active 3/87)
- EURUSDm/USDCHFm: {'adf': 78, 'coint': 78, 'half_life': 7} (active 1/87)
- USDCADm/USOILm: {'adf': 79, 'coint': 86, 'half_life': 3} (active 1/87)
- XAUUSDm/XAGUSDm: {'adf': 83, 'coint': 82, 'half_life': 5} (active 1/87)
- US30m/US500m: {'adf': 82, 'coint': 73, 'half_life': 13} (active 3/87)
- USTECm/US500m: {'adf': 85, 'coint': 81, 'half_life': 6} (active 1/87)
- BTCUSDm/ETHUSDm: {'adf': 101, 'coint': 95, 'half_life': 23} (active 1/104)

## Interpretation guards (frozen)

- PARKED / REJECTED / CANDIDATE / INCONCLUSIVE are **research-family verdicts**
  about this replica pipeline on this data — never verdicts on the
  frozen R4 production strategy.
- One preregistered trial slot (R4-B2) consumed by this family verdict;
  any gate/window/universe change requires a NEW preregistration.
- The parking rule was registered BEFORE execution; it is not a post-hoc
  stopping choice.
- INCONCLUSIVE is never read as a pass; no VALIDATED verdict exists.
- Pair selection was by declared economic rationale, not by scanning
  cointegration statistics (no pair-mining).

*Artifacts: r4_b2_pairs_report.json + per-pair trade CSVs in reports/r4_mean_reversion/.*
