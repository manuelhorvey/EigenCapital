# HYP-SA-003 — Density-Clustered Pairs (DBSCAN/HDBSCAN)

```text
hypothesis_id:        HYP-SA-003
title:                Clustering return-series similarity (DBSCAN/HDBSCAN) yields
                      pair candidates whose tradeable performance matches or beats
                      sector-based pair selection
hypothesis_family:    statistical_arbitrage
status:               UNVALIDATED
trial_group_default:  HYP-SA-003/cluster-param-grid
source:               docs/research/ml4t-extraction.md (Jansen Ch 13 density clustering)
```

## Claim

Data-driven clusters of similar return behavior identify economically linked
pairs without imposing sector taxonomy — expanding the candidate pool at equal
or better quality.

## Economic Rationale

Behavioral linkage (similar investor bases, factor loadings, supply chains)
manifests in co-movement before it appears in static classifications; clustering
recovers these latent groups. Caveat carried by this hypothesis: correlation is
necessary but not sufficient for economic linkage — selection must still filter
for plausibility.

## Expected Mechanism

Cluster on rolling-correlation/distance features → within-cluster pairs enter
the HYP-SA-001 pipeline; compare out-of-sample performance vs sector-only pairs.

## Universe

Liquid equities with sufficient history for stable distance estimates.

## Required Data

Adjusted prices; sector labels for the comparison arm.

## Candidate Features

- Correlation-distance matrix `sqrt((1-corr)/2)`
- Cluster stability score across windows

## Candidate Parameters (declares trial search space)

- algorithm: {DBSCAN eps-scan, HDBSCAN min-cluster-size}
- feature window: {252}

## Expected Failure Modes

- Spurious clusters of merely co-trending names → broken spreads in regime shifts
- Cluster instability across estimation windows
- Selection bias explosion: cluster grid × pair grid multiplies trial count —
  trial accounting here is not optional

## Falsification Criteria

Reject if ANY of:
- No out-of-sample improvement over sector-based arm after costs
- Pair survival rate (still cointegrated next window) worse than sector arm
- Performance concentrated in unstable clusters

## Transaction Cost Sensitivity

As HYP-SA-001.

## Capacity Considerations

As HYP-SA-001.
