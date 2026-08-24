# HYP-ALT-003 — News Topic Novelty

```text
hypothesis_id:        HYP-ALT-003
title:                The arrival of previously unseen topics in an asset's news flow
                      predicts short-horizon volatility expansion and directional
                      drift in the topic's sentiment direction
hypothesis_family:    alternative_data
status:               UNVALIDATED
trial_group_default:  HYP-ALT-003/novelty-definition-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 15 topic modeling)
```

## Claim

Topic-model novelty (new theme entering the news distribution for an asset)
signals regime-relevant information; markets underreact to genuinely new
narratives relative to repeated ones.

## Economic Rationale

Attention is finite: novel narratives propagate through investor subsets
sequentially (diffusion), while repeated topics are already priced. Novelty
distinguishes information shocks from noise.

## Expected Mechanism

Novelty event → vol expansion (robust) + directional drift aligned with topic
sentiment (weaker, conditional). The vol claim is tested first as it is stronger.

## Universe

News-covered liquid equities.

## Required Data

Timestamped news corpus with publication times; topic model version frozen per
experiment; prices for evaluation.

## Candidate Features

- Min cosine distance of article embedding to asset's trailing topic centroid
- New-topic count per {5, 21} day window

## Candidate Parameters (declares trial search space)

- novelty definition: {distance threshold, count}
- horizon: {1, 5, 10} days

## Expected Failure Modes

- Look-ahead via corpus timestamp errors (top risk — vendor backfill)
- Topic drift making "novelty" non-stationary
- Sentiment-direction component likely absorbed by existing momentum/sentiment
  hypotheses

## Falsification Criteria

Reject if ANY of:
- Vol-expansion effect absent after conservative timestamp lagging (kills even
  the strong form)
- Directional increment over HYP-MOM-003/HYP-ALT-001 controls absent
- Non-monotone relation between novelty magnitude and response

## Transaction Cost Sensitivity

High at daily frequency; viable mainly as conditioning/overlay signal.

## Capacity Considerations

Low standalone; overlay framing preferred.
