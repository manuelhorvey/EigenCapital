# HYP-FACTOR-001 — PCA Eigenportfolios

```text
hypothesis_id:        HYP-FACTOR-001
title:                Principal components of the normalized-return covariance
                      matrix, used as portfolio weights (eigenportfolios), produce
                      uncorrelated sleeves with distinct, persistent return patterns
hypothesis_family:    factor
status:               UNVALIDATED
trial_group_default:  HYP-FACTOR-001/component-window-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 13 eigenportfolios)
```

## Claim

Standardized principal components of asset-return covariance are investable
portfolios; beyond PC1 (the market proxy), higher components capture persistent
sector/style structure exploitable as allocation sleeves or risk controls.

## Economic Rationale

Covariance structure encodes the economy's risk-sharing topology; eigenvectors
are its natural coordinates. Data-driven factors require no ex-ante labels and
adapt to structural change — the complement to HYP-FACTOR-003's published factors.

## Expected Mechanism

PC1 tracks the market (~40-55% of variance); PC2+ behave like sector/style
tilts with low mutual correlation; sleeve correlations to each other < threshold
is the operative claim.

## Universe

Top-liquidity equities (PCA is outlier-sensitive: winsorize per extraction doc;
missingness rules per Jansen's 95% thresholds).

## Required Data

Adjusted daily returns for a stable universe; enough cross-section (≥ 30 names).

## Candidate Features

- Eigenvector weights from rolling covariance windows

## Candidate Parameters (declares trial search space)

- window: {252, 504} days
- components held: {2..5}
- normalization: {unit-sum weights}

## Expected Failure Modes

- Eigenvector sign/order instability across windows → turnover spikes
- Estimation noise in small samples distorts tail components
- Non-stationarity of "sector" components as economies rotate

## Falsification Criteria

Reject if ANY of:
- Sleeve pairwise correlations exceed declared threshold out-of-sample
  (components not distinct)
- Higher-component sleeves fail to beat equal-weight benchmark after costs
- Weight instability makes implementation cost-prohibitive at baseline costs

## Transaction Cost Sensitivity

Moderate; driven by eigen-decomposition churn between rebalances.

## Capacity Considerations

Moderate-high on large-cap universes.
