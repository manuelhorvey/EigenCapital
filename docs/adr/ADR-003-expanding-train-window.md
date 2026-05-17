# ADR-003: Expanding Train Window Over Rolling for Walk-Forward Validation

**Status:** Accepted

## Context

The walk-forward validation framework needed a policy for how training data accumulates over time. Two approaches were tested: rolling window (train on the most recent N years, drop older data) and expanding window (accumulate all historical data, never drop old observations). Both were evaluated using the same XGBoost multiclass pipeline on XLF (2016-2024). The rolling window used 18 months of training data with a 1-year test window and 1-year step.

## Decision

Adopt expanding (growing) training window. Training accumulates from the start date forward: the 2022 test window trains on 2016-2021, the 2023 test window trains on 2016-2022, etc. The walk-forward implementation in `WalkForwardValidator` (`backtests/walk_forward.py`) computes `train_mask = (X.index.year <= train_end)` — all data up to year N-1. Combined with recency-weighted training samples (linear decay 1.0 → 0.5 from newest to oldest) and regime-weighted sample weights (TREND=1.0, RANGE=0.8, VOLATILE=0.6, NEUTRAL=0.5).

## Alternatives Considered

- **Rolling 18-month window:** Produced average expectancy of -0.000192, profit factor 0.91, and only 6 of 16 test windows positive. The rolling window discarded macro-regime context — a 2023 model trained only on 2021-2022 data never experienced a low-rate, low-vol environment and was permanently biased.
- **Rolling 36-month window:** Better but still inferior to expanding. Less regime diversity in training.
- **Fixed 3-year window:** Tested in early walk_forward.py version; 2022 window showed long bias because it trained on 80% bull market data.

## Consequences

**Positive:** Expanding window captures multiple macro regimes in training data — rate hiking cycles, low-vol periods, COVID dislocation. The 2023 window trained on 2017-2022 (includes 2018 rate hikes, 2020 crash, 2022 tightening), producing PF=1.23 vs the 3-year window's PF=0.90. Recency weighting prevents old data from dominating.

**Negative:** Computational cost grows over time. The 2024 test window must train on ~8 years of data. The weekly retrain pipeline (`rolling_retrain_weekly.py`) mitigates this by incremental training. There is also a regime-shift risk: if 2008-style data is permanently irrelevant to 2025 markets, the expanding window cannot forget it. The recency weighting partially addresses this but does not solve it.

## Evidence

Rolling 18-month: avg expectancy -0.000192, PF 0.91, 6/16 positive.
Expanding window: 2019-2024 average PF 1.16, Sharpe 0.65, 5/6 years positive.
The 2023 transition is the clearest signal: 3-year window PF=0.90 → 5-year window PF=1.23. The extra two years (2018 rate hike cycle) provided the model with relevant tightening-regime experience that the 2022-2023 rally conditions required.
