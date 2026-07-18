# EigenCapital — Known Issues & Constraints

> Resolved issues are tracked in [`CHANGELOG.md`](../CHANGELOG.md). This file
> documents only currently-open constraints.

| # | Issue | Impact | Mitigation |
|---|-------|--------|------------|
| 1 | **Paper trading only** — MT5 Exness demo (~$107), no live capital deployed | No real PnL; MT5 orders quantize to 0.01 lots | Defer live deployment until equity > $10K |
| 2 | **6 permanent SELL_ONLY assets** — CADCHF, EURAUD, EURCHF, GBPCHF, GBPJPY, NZDCHF have confirmed permanent BUY signal inversion | BUY signals are overridden to FLAT for these assets | See AGENTS.md for full diagnostic chain |
| 3 | **MT5 bridge requires Wine** on Linux; single-threaded (RLock) | Concurrent requests serialized; 5s socket timeout on price fetch | Acceptable for paper trading |
| 4 | **Spread gate observe mode** — first 720 cycles (~6h) log-only | No entry blocking during warmup window | Enforcement activates automatically after observation window |
| 5 | **First-cycle cold-start transient** — cycle 1 uses 200 data rows (truncation validation hasn't run) | Regime output differs from cycles 2+ | Suppressed by `apply_first_cycle_suppression` stage |
| 6 | **Paper/MT5 sizing divergence** — paper simulates $100K equity, MT5 executes on ~$107 | Two completely independent sizing chains produce different position sizes | Expected behavior |
| 7 | **BUY inversion root cause unknown** — SELL_ONLY filter is empirically correct but the underlying cause of inverted BUY calibration is unidentified | No path to two-way trading for 6 permanent assets | Two leading hypotheses (carry, DXY) falsified by walk-forward ablation |
| 8 | **JPY/CHF cross TZ issue** — incomplete daily bar on first cycle | Resolves after next cycle with full bar | UTC normalization + index deduplication applied |

---

**Last updated:** 2026-07-18
