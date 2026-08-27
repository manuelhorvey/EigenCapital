# Intraday Research Campaigns

This directory contains sequential intraday research campaigns. Each campaign builds on the previous, testing increasingly refined hypotheses about intraday momentum and mean-reversion signals.

## Campaign Lineage

| Campaign | Timeframe | Purpose | Key Files |
|----------|-----------|---------|-----------|
| **Campaign 1** | Daily | Baseline momentum research | `campaign.py` |
| **Campaign 2** | 1-minute | Microstructure signal discovery | `campaign2.py`, `run_campaign2.py` |
| **Campaign 3** | 5-minute | Hypothesis validation framework | `campaign3.py`, `campaign3_hypotheses.py` |
| **Campaign 3 Full** | 5-minute | Extended hypothesis testing | `campaign3_full.py`, `campaign3_full_hypotheses.py` |
| **Campaign 4** | 15-minute | Primary intraday hypothesis testing | `campaign4_15m.py` |
| **Campaign 5** | 30-minute | Multi-timeframe confirmation | `campaign5_30m.py` |
| **Campaign 6** | 1-hour | Confirmation and robustness | `campaign6_1h_confirmation.py` |
| **Campaign 7** | Micro | Micro-regime classification | `campaign7_micro.py` |
| **Campaign 7 Rerun** | Micro | Hardened re-validation | `campaign7_rerun_hardened.py` |
| **Campaign 8** | TF003 | Final confirmation campaign | `campaign8_tf003_confirmation.py` |

## Data Pullers

- `data_puller.py` — Daily data fetcher
- `m1_data_puller.py` — 1-minute data fetcher
- `m15_data_puller.py` — 15-minute data fetcher
- `m30_data_puller.py` — 30-minute data fetcher
- `tick_data_puller.py` — Tick data fetcher

## Shared Infrastructure

- `hypotheses.py` — Hypothesis definitions
- `sessions.py` — Trading session definitions
- `net_accounting.py` — Net P&L accounting
- `run_campaign.py` — Campaign runner

## Dependency Graph

```
campaign4_15m ← campaign5_30m ← campaign6_1h_confirmation
                    ↑                    ↑
              campaign7_micro ← campaign8_tf003_confirmation
                    ↑
          campaign7_rerun_hardened
```

## Tests

Tests are in `tests/unit/research/intraday/`:
- `test_campaign4.py` — Campaign 4 tests
- `test_campaign5.py` — Campaign 5 tests
- `test_campaign6.py` — Campaign 6 tests
- `test_campaign7.py` — Campaign 7 tests
- `test_campaign8.py` — Campaign 8 tests
- `test_campaign7_rerun.py` — Campaign 7 rerun tests
- `test_accounting_contract.py` — Accounting contract tests
