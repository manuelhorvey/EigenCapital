# HYP-ALT-002 — SEC Filing Language Shift

```text
hypothesis_id:        HYP-ALT-002
title:                Changes in risk-factor/MD&A language between consecutive 10-Ks
                      predict deteriorating fundamentals and negative drift
hypothesis_family:    alternative_data
status:               UNVALIDATED
trial_group_default:  HYP-ALT-002/embedding-method-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 16 SEC-filing embeddings)
```

## Claim

Semantic shifts in mandatory disclosures — especially new/negative risk-factor
content — lead fundamental deterioration that prices absorb slowly.

## Economic Rationale

Disclosure is legally constrained language; firms reveal adverse conditions in
prose before they appear in numbers. Embedding distances capture these shifts
without hand-built dictionaries.

## Expected Mechanism

Filing-to-filing embedding distance (or risk-section tone delta) → negative
forward returns over {1, 2, 3} quarters post-filing.

## Universe

US-listed filers with consecutive annual filings.

## Required Data

EDGAR filings with filing timestamps (authoritative — EDGAR timestamps are the
gold standard for point-in-time discipline); embedding model version pinned.

## Candidate Features

- Cosine distance between filing embeddings year-over-year
- Risk-factor section length/tone deltas

## Candidate Parameters (declares trial search space)

- representation: {tf-idf, word2vec-class, transformer}
- section: {risk factors, MD&A}

## Expected Failure Modes

- Boilerplate inflation decoupling language from substance
- Model-version drift breaking comparability across filings (version must be
  frozen per experiment)
- Confusion with size/sector effects

## Falsification Criteria

Reject if ANY of:
- No monotonic relation between language-shift magnitude and forward returns
- Effect absorbed by existing factor controls
- Results not robust to embedding method swap (method artifact)

## Transaction Cost Sensitivity

Low (annual signal) — favorable turnover profile for an alt-data candidate.

## Capacity Considerations

High on covered universe.
