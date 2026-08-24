# Research Hypotheses

Candidate research claims. **Hypotheses are NOT strategies.**

> A hypothesis states a testable claim about market behavior and how it would be
> falsified. "Medium-term momentum should persist because information diffuses
> gradually and investors underreact" is a hypothesis. "60-day return > 0 → buy"
> is an implementation. They remain separate until Phase 1G infrastructure
> exists to connect them honestly.

## Governance

1. **Do not run these yet.** Execution requires Phase 1G statistical validation
   infrastructure (purged/embargoed CV, cost-adjusted backtesting under
   [RESEARCH_ENGINE_CONTRACT.md](../../docs/RESEARCH_ENGINE_CONTRACT.md)).
2. Every stub below enters as `status = UNVALIDATED`. Nothing here carries
   implied alpha — these are candidates for aggressive rejection.
3. `economic_rationale` and `falsification_criteria` are mandatory. A claim
   without a falsifier is not admissible.
4. Each experiment spawned from a hypothesis MUST carry `TrialMetadata`
   (`trial_group_id`, `trial_index`, `selection_method`, ...) per the Trial
   Accounting section of the research engine contract.
5. Provenance: most seeds derive from [ml4t-extraction.md](../../docs/research/ml4t-extraction.md)
   (Jansen 2020, read as reference material — not architectural authority).
   The authoritative specs remain SYSTEM_SPECIFICATION.md, domain_contracts.md,
   and the EigenCapital contracts.

## Status Lifecycle

```text
UNVALIDATED → REGISTERED → EXPERIMENTED → SUPPORTED | REJECTED
                                  └────────────→ REJECTED (default outcome)
```

Only survivors become strategy candidates. Reject aggressively.

## Families

| Directory | Claim domain |
|---|---|
| `trend/` | Time-series momentum, acceleration, distance-from-extreme |
| `momentum/` | Cross-sectional momentum variants |
| `mean_reversion/` | Short-horizon reversal, oscillator, relative-value spreads |
| `breakout/` | Range/level break continuation |
| `volatility/` | Low-risk anomalies, vol structure |
| `cross_sectional/` | Fundamental tilts (quality, accruals, yield) |
| `statistical_arbitrage/` | Cointegration/pairs structures |
| `factor/` | Data-driven risk factors and baselines |
| `ml/` | ML signal aggregation (gated behind 1G + simplicity ladder) |
| `alternative_data/` | Text/sentiment-derived signals |
