# ADR-013: Bootstrap Validation as Deployment Gate

**Status:** Accepted

## Context

Walk-forward profit factor (PF) alone is not sufficient to distinguish signal from noise. The 2022 XLF test window produced PF=0.98 — slightly below breakeven, seemingly a marginal failure. A standard evaluation would flag this year as bad but might consider it within normal variance. The 2024 window produced PF=1.34 — clearly positive. The question was whether PF=0.98 represents a genuine edge failure or random noise. A bootstrap permutation test was run on each test window: the model's predictions were shuffled (destroying the time-series link between prediction and outcome) and PF was recomputed 10,000 times. The p-value represents the probability of achieving the observed PF by random chance.

## Decision

Adopt bootstrap p < 0.10 as a deployment gate for each walk-forward test window. A test window that does not meet this threshold is classified as noise regardless of its raw PF. The bootstrap is implemented as a permutation test: 10,000 shuffles of the label-signal alignment, PF computed for each shuffle, p = (1 + count(PF_shuffled >= PF_observed)) / (1 + n_shuffles). The gate applies per window: the 2024 window (PF=1.34, p=0.047) passes — the model has genuine signal. The 2022 window (PF=0.98, p=0.571) fails — the result is indistinguishable from random noise. A minimum of 4 of 6 test windows must pass the bootstrap gate for an asset to be deployable.

## Alternatives Considered

- **PF > 1.10 threshold only:** PF=0.98 in 2022 would be correctly rejected, but PF=1.34 in 2024 would be accepted on faith. Bootstrap adds statistical rigor to both rejections and acceptances.
- **Sharpe ratio p-value:** Tested but Sharpe requires normality assumptions that financial returns violate. Bootstrap is distribution-free.
- **Deflated Sharpe ratio (DSR):)** Would account for multiple testing (6 windows × multiple assets) but adds complexity and is better suited to strategy selection than deployment gating.
- **No statistical gate:** Risk of deploying strategies that appear profitable but are actually noise — precisely the pattern that generated the 0/7 NZDJPY results.

## Consequences

**Positive:** Prevents deployment of statistically invalid windows. The 2022 PF=0.98, p=0.571 result would have been a real-money loss if deployed without the gate. The 4/6 window minimum requirement ensures that the overall performance is not driven by a single lucky year. Bootstrap is non-parametric and makes no distributional assumptions.

**Negative:** 10,000 bootstrap shuffles per window × 6 windows = 60,000 model evaluations per asset. This is computationally intensive (minutes per asset). The p < 0.10 threshold is arbitrary — more conservative (p < 0.05) would reject more windows but might reject genuinely profitable years in small samples. The 4/6 minimum windows requirement may reject profitable strategies with one or two unlucky years.

## Evidence

2022 XLF window: PF=0.98, bootstrap p=0.571 (noise — do not deploy).
2024 XLF window: PF=1.34, bootstrap p=0.047 (signal — deployable).
The bootstrap gate prevented deploying the 2022 model configuration (which would have lost money). It confirmed the 2024 configuration (which generated 21.95% net return). Without the gate, both windows would have been aggregated into an average and the noise in 2022 would have been hidden.
