# ADR-008: Five-Year Training Window Over Three-Year for Equity Walk-Forward

**Status:** Accepted

## Context

The walk-forward training window length determines how much historical data the model sees before each test year. The 3-year window (36 months) was the initial default based on the belief that recent data is most relevant and older regimes are structurally obsolete. During evaluation, the 3-year window produced a notable failure: the 2022 test year showed PF=0.96 because the model trained on 2019-2021 data (80% bull market, near-zero rates, low volatility) was structurally long-biased heading into the 2022 rate hiking cycle. The model had never experienced a tightening regime.

## Decision

Adopt a 5-year training window (60 months) for the primary XLF walk-forward. The 5-year window includes 2017-2018 (a prior rate hiking cycle), 2019 (pause/cut), 2020 (COVID crash and recovery), and 2021 (reflation). This ensures the training data includes at least one full rate cycle for the equity macro features. Combined with the expanding window policy (ADR-003), the effective training window expands beyond 5 years as the walk-forward progresses (2024 model trains on 2016-2023: 8 years, three distinct macro regimes).

## Alternatives Considered

- **3-year window:** 2022 PF=0.96 (long bias in bear market). 2023 flipped from PF=0.90 to PF=1.23 after extending to 5 years.
- **7-year window:** Tested but showed diminishing returns — the additional years (2015-2016) added zero-rate regime data that was similar to 2019-2020. The marginal benefit of years beyond 5 decreases.
- **Adaptive window (longer in low-vol, shorter after regime change):)** Rejected as too complex — the regime classifier already handles transitions; adding adaptive window selection introduces another tuning dimension.

## Consequences

**Positive:** The 5-year window ensures at least one full rate cycle in training. The model learned to handle tightening regimes from the 2018 experience. The 2022 test year PF improved from 0.96 (3yr) to 1.03 (5yr with expanding). The 2023 test year showed the largest gain: PF=0.90 → 1.23.

**Negative:** 5-year window + 1-year step + 6 test years (2019-2024) requires 6 training runs, each on an accumulating dataset. Computational cost is higher than 3-year but manageable (minutes per run on XLF's ~1250 daily bars). There is also a data-availability constraint: for new assets with less than 5 years of history, this window cannot be used.

## Evidence

3-year window: 2022 PF=0.96 (long bias wrong), 2023 PF=0.90 (lagging recovery). 5-year window: 2022 PF=1.03 (marginal but positive), 2023 PF=1.23 (correctly captured transition). The 2018 rate hike cycle in the expanded training data provided the model with experience of how XLF behaves during tightening — the causal patterns (flattening yield curve, rising rate_diff, sector underperformance) were present in 2018 and reusable in 2022-2023.
