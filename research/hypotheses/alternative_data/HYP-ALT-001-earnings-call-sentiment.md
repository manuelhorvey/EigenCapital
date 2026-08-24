# HYP-ALT-001 — Earnings-Call Sentiment

```text
hypothesis_id:        HYP-ALT-001
title:                Management tone in earnings calls (measured at publication
                      time) predicts abnormal returns around and after the following
                      earnings event
hypothesis_family:    alternative_data
status:               UNVALIDATED
trial_group_default:  HYP-ALT-001/sentiment-method-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 14, 16; call transcripts)
```

## Claim

Tone shifts in prepared remarks/Q&A contain incremental information about future
fundamentals that the market prices slowly.

## Economic Rationale

Management possesses superior information; linguistic hedging/evasion patterns
leak it before numbers do. Investors overweight headline numbers relative to
language cues → underreaction to tone.

## Expected Mechanism

Negative tone change → subsequent negative drift, strongest into the next
earnings announcement; Q&A often more informative than prepared text (testable).

## Universe

Equities with transcript coverage; coverage bias documented.

## Required Data

Transcripts with publication timestamps (point-in-time mandatory); prices;
optionally analyst consensus for controls.

## Candidate Features

- Dictionary-based tone delta (Loughran-McDonald-class finance lexicon)
- Model-based sentiment score (fine-tuned classifier) — only after dictionary
  arm establishes baseline

## Candidate Parameters (declares trial search space)

- method: {lexicon, classifier}
- window: {quarterly delta, level}

## Expected Failure Modes

- Transcript timestamp violations (pre-release access) — fatal look-ahead risk
- Sentiment correlated with momentum/revision signals already in library
  (increment must be shown)

## Falsification Criteria

Reject if ANY of:
- No drift increment after conservative publication lagging
- No increment over HYP-MOM-003 revision-breadth control
- Effect confined to small-caps with negligible capacity

## Transaction Cost Sensitivity

Event-clustered; moderate-high.

## Capacity Considerations

Coverage-limited; mid/large-cap biased.
