# R4-B1 — Mean Reversion / Stat-Arb Pairs (OBSERVED report)

**Experiment:** R4-B1 mean-reversion / stat-arb preregistered pairs  
**Contract:** `docs/research/R4_MEAN_REVERSION.md` (frozen before code; pre-execution addendum)  
**Run:** 2026-09-17T15:31:16.826950+00:00 · deterministic (seeded permutation only)  
**Universe:** r4_local_v1 — pairs: AUDUSDm/NZDUSDm, EURUSDm/GBPUSDm  
**OOS split:** exit bar index ≥ 765 (frozen R3 WF geometry)  
**Costs:** 60 bps per round trip (4 legs × 15 bps)

> **What this is:** a research-only mean-reversion/stat-arb family
> evaluated against its preregistered falsification arms.
> **What this is NOT:** a statement about the frozen R4 production
> strategy, and not a promotion decision.

## Verdict: **INCONCLUSIVE**

> the family verdict is INCONCLUSIVE — sample gate (≥ 20 round-trips) failed on every pair; F-A: insufficient OOS trades for the permutation test. Missing evidence is never promoted to a pass..

## Falsification arms

- **F-A** (OOS gross per-trade edge, sign-flip permutation): p = None over 1 OOS trades
- **F-B** (OOS net P&L after full costs): -0.0039
- **F-C** (correlation with frozen-R4 replica < 0.7): rho = 8.957225614485334e-05 over 1826 overlap days

## Per-pair diagnostics

| Pair | bars | est. dates | active | trades (IS/OOS) | gate≥20 | net P&L | hit rate | cancelled | WF windows | WF mean OOS Sharpe |
|---|---|---|---|---|---|---|---|---|---|---|
| AUDUSDm/NZDUSDm | 2076 | 87 | 0 | 0/0 | FAIL | 0.0000 | 0.000 | 0 | 4 | 0.000 |
| EURUSDm/GBPUSDm | 2076 | 87 | 3 | 0/1 | FAIL | -0.0039 | 0.000 | 0 | 4 | 0.058 |

Gate failures by type (across estimation dates):

- AUDUSDm/NZDUSDm: {'adf': 87, 'coint': 78, 'half_life': 6} (active 0/87)
- EURUSDm/GBPUSDm: {'adf': 78, 'coint': 76, 'half_life': 0} (active 3/87)

## Interpretation guards (frozen)

- REJECTED / CANDIDATE / INCONCLUSIVE are **research-family verdicts**
  about this replica pipeline on this data — never verdicts on the
  frozen R4 production strategy.
- One preregistered trial slot is consumed by this family verdict;
  threshold or universe changes require a NEW preregistration.
- INCONCLUSIVE is never read as a pass; no VALIDATED verdict exists.
- Promotion question is incremental portfolio utility (F-C), not
  standalone return parity with R4.

*Artifacts: r4_b1_pairs_report.json + per-pair trade CSVs in reports/r4_mean_reversion/.*
