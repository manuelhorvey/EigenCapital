# INTRADAY RESEARCH LEDGER — FINAL

**Status:** 🔒 Branch exhausted and frozen as of 2026-08-25
**Scope:** All intraday alpha research in the Exness 8-instrument universe,
from M1 OHLCV through broker-quote microstructure.

This ledger is authoritative history. It exists so that no future session
re-litigates frozen results without *new information sources*, and so the
falsification record remains auditable.

---

## 1. Program scoreboard

| # | Campaign | Information source | Evaluations | Supported | Outcome |
|---|---|---|---|---|---|
| 1 | M5 price-based | OHLCV M5 | 24 | 0 | ❌ Frozen |
| 2 | M5 microstructure proxies | OHLCV+volume M5 | 20 | 0 | ❌ Frozen |
| 3 | M1 order-flow proxies | OHLCV M1 | 16 | 0 (1 fragile) | ❌ Frozen |
| 4 | 15M multi-family discovery | OHLCV M15 | 31 | 0 (10 fragile) | ❌ Frozen |
| 5 | 30M mechanism-focused | OHLCV M30 | 18 | **1** (ST-001) | 🟡 → killed by C6 |
| 6 | 1H ST-001 confirmation | OHLCV H1, 8 years | 24 | 0 | ❌ NOT_CONFIRMED |
| 7 | Broker microstructure | Real quote ticks → M5 micro bars | 18×4 = 72 | 1 raw (TF-003) | ❌ Frozen by rerun |
| 7R | Hardened-governance rerun | same snapshot | 72 | **0** | ❌ Frozen |
| | **Total governed evaluations** | | **205** | **0 final** | |

## 2. Three distinct falsification modes demonstrated

1. **Cross-timeframe confirmation failure** — ST-001 passed every frozen gate
   at 30M (net +0.304 Sharpe, p=0.02, 8/8 instruments positive) but the exact
   pre-registered translation to 1H on 8 years of data was net-negative at all
   horizons. Lesson: a timeframe-specific expression is not a mechanism.
2. **Multiple-testing correction failure** — TF-003's raw permutation p=0.03
   became p_family=1.000 under Bonferroni across its own 72-evaluation family,
   and p_cumulative=1.000 against the program ledger of 205 trials.
3. **Economic-viability failure** — TF-003's gross Sharpe of +2.18 proves real
   short-horizon predictiveness, but ~1.7bp of edge per flip cannot pay ≥13bps
   round-trip costs at 65K flips/year: corrected net accounting yields a cost
   drag ≈ 40× gross alpha.

The system also caught and repaired its own measurement defect: Campaigns 4–7
initially computed Sharpe on gross per-bar returns while deducting costs only
from total return. The corrected engine (`campaign8_tf003_confirmation.bt_corrected`,
locked by unit tests) is now the mandatory primitive — see
[RESEARCH_ACCOUNTING_CONTRACT.md](../RESEARCH_ACCOUNTING_CONTRACT.md).

## 3. What is frozen (do not reopen)

- All bar timeframes M1–1H for OHLCV/session/price-structure/volume-proxy
  mechanisms in this universe.
- ST-001 in any form (no lookback/boundary/horizon/universe tuning).
- TF-003 and all Campaign 7 signal families on this broker's quote flow.
- Any "search another timeframe" campaign without a new information source.

Reopening criteria (all required):
1. A genuinely new information source (institutional order-flow data,
   broker-independent feeds, options/implied vol, news/event structure,
   cross-market data) with an economic rationale pre-registered before pull.
2. Cumulative trial count carried forward (thresholds harden).
3. Corrected accounting engine from the first bar.
4. Fresh, untouched data window for any confirmation leg.

## 4. What survives as assets

- **Validation infrastructure**: purged walk-forward, permutation testing,
  Bonferroni family correction, cumulative trial ledger, corrected cost
  engine, immutable data snapshots with hashes.
- **Forensic knowledge**: session structure exists but is thin; quote-flow
  predictiveness is real at ≤5-minute horizons in this broker's stream;
  retail spread levels make sub-15-minute turnover economics prohibitive.
- **R4 swing/daily track**: fully intact, qualified through micro-live; the
  engineering effort belongs there (Phase 1U production qualification).

## 5. Artifact index

| Artifact | Path |
|---|---|
| Timeframe freeze declaration | [INTRADAY_TIMEFRAME_BRANCH_FROZEN.md](INTRADAY_TIMEFRAME_BRANCH_FROZEN.md) |
| Campaign reports | `reports/campaign*_*.md` / `.json` |
| Corrected engine + locks | `src/eigencapital/research/intraday/campaign8_tf003_confirmation.py`, `tests/unit/research/intraday/test_campaign8.py` |
| Hardened governance | `src/eigencapital/research/intraday/campaign7_rerun_hardened.py`, `tests/unit/research/intraday/test_campaign7_rerun.py` |
| Data snapshots | `data/intraday_m1|m15|m30|intraday_h1|tick_micro_m5/` (+ manifests) |
