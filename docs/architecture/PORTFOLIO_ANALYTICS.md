# Portfolio Analytics — Shadow Measurement Layer

> **SHADOW-ONLY — NO EXECUTION AUTHORITY**
>
> This module observes, calculates, persists, visualizes, and generates research evidence.
> It may NOT modify:
> - Signal weights
> - Selection logic
> - Position sizing
> - Order quantity
> - Execution sequence
> - Risk approval
> - Broker state

---

## Architecture

```
                 FROZEN R4
                     │
                     ▼
              LIVE EXECUTION
                     │
          ┌──────────┴──────────┐
          │                     │
          ▼                     ▼
      REAL P&L              SHADOW ANALYTICS
                                │
               ┌────────────────┼────────────────┐
               ▼                ▼                ▼
          Concentration       Factors        Correlation
               │                │                │
               └────────────────┼────────────────┘
                                ▼
                         Evidence Ledger
                                │
                                ▼
                         PHASE 2 VERDICT
```

## Metrics

### Exposure

| Metric | Definition | Unit |
|--------|-----------|------|
| `gross_exposure` | Sum of absolute notionals across all positions | USD |
| `net_exposure` | Long notional minus short notional | USD |
| `long_exposure` | Sum of long position notionals | USD |
| `short_exposure` | Sum of short position notionals | USD |
| `gross_leverage` | `gross_exposure / equity` | ratio |
| `net_leverage` | `net_exposure / equity` | ratio |

### Concentration (Weight-Based, No Correlation)

| Metric | Definition | Unit |
|--------|-----------|------|
| `max_position_weight` | Largest single position weight | ratio |
| `max_position_symbol` | Symbol of largest position | string |
| `top3_concentration` | Sum of 3 largest position weights | ratio |
| `top5_concentration` | Sum of 5 largest position weights | ratio |
| `herfindahl_index` | HHI = Σ(w_i²) | ratio |
| `effective_positions` | 1/HHI — weight concentration only | count |

**Important:** `effective_positions` measures weight concentration, NOT correlation-aware diversification. A portfolio with 10 equal-weight positions has `effective_positions ≈ 10` regardless of how correlated those positions are.

### Factor Exposure

#### Currency Factors

| Factor | Exposure Calculation |
|--------|---------------------|
| Long EURUSD | +EUR notional, -USD notional |
| Short EURUSD | -EUR notional, +USD notional |
| Long GBPJPY | +GBP notional, -JPY notional |

Metrics:
- `currency_exposure` — notional per currency (USD, EUR, GBP, AUD, NZD, CAD, CHF, JPY)
- `currency_exposure_pct` — exposure as % of equity
- `largest_currency_factor` — currency with largest absolute exposure
- `largest_currency_factor_pct` — magnitude of largest factor

#### Asset Classes

| Class | Symbols |
|-------|---------|
| `forex` | All currency pairs |
| `crypto` | BTCUSD, ETHUSD |
| `metals` | XAUUSD, XAGUSD |
| `indices` | US30, USTEC |
| `energy` | USOIL |

Metrics:
- `asset_class_exposure` — notional per asset class
- `asset_class_exposure_pct` — exposure as % of equity
- `largest_asset_class` — class with largest exposure
- `largest_asset_class_pct` — magnitude

### Dependence (Correlation-Aware)

| Metric | Definition | Requirement |
|--------|-----------|-------------|
| `avg_pairwise_correlation` | Mean of off-diagonal correlation matrix entries | Returns history ≥ 30 days |
| `effective_bets` | (Σw_i)² / (w'Σw) — accounts for correlation | Returns history ≥ 30 days |
| `high_corr_clusters` | Pairs with \|correlation\| > 0.7 | Returns history ≥ 30 days |
| `cluster_count` | Number of high-correlation clusters | Returns history ≥ 30 days |
| `market_factor_fraction` | Largest eigenvalue / total variance | Returns history ≥ 30 days |

**Important distinction:**
- `effective_positions` = 1/HHI — weight concentration only
- `effective_bets` = correlation-adjusted — accounts for dependence

When negative correlations exist, `effective_bets` can exceed `effective_positions` because negative correlations REDUCE portfolio variance.

### Counterfactuals (What-If, Never Executed)

| Portfolio | Method |
|-----------|--------|
| `equal_weight` | Equal allocation across all positions |
| `inverse_volatility` | Weight ∝ 1/volatility (requires returns) |
| `factor_equal_currency` | Equal exposure per currency factor |

## Methodology Metadata

Every analytics record includes methodology metadata for reproducibility:

```json
{
  "methodology": {
    "correlation_window": "60d",
    "correlation_method": "pearson",
    "return_frequency": "daily",
    "min_observations": 30,
    "eigenvalue_method": "symmetric_eigendecomposition",
    "effective_bets_definition": "(sum(w_i))^2 / (w' * Sigma * w)",
    "weight_basis": "actual_notional",
    "price_timestamp": "tick_at_execution",
    "analytics_version": "1.0"
  }
}
```

## Data Quality Behavior

| Condition | Behavior |
|-----------|----------|
| Returns history < 30 days | Correlation diagnostics returned as empty `{}` |
| Returns contain NaN | Correlation computation skipped (returns empty) |
| Returns contain Inf | Correlation computation skipped (returns empty) |
| Singular correlation matrix | Computation skipped (returns empty) |
| Single position | Concentration metrics computed; no correlation needed |
| Empty portfolio | All metrics zero/empty |

## Usage

```python
from eigencapital.live.portfolio_analytics import PortfolioAnalyzer

analyzer = PortfolioAnalyzer(audit_dir="reports/r4_loop")

# After computing target weights and generating orders
diagnostics = analyzer.compute_diagnostics(
    target_weights=latest_weights,
    current_positions=current_lots,
    prices=prices,
    contract_sizes=contract_sizes,
    equity=equity,
    returns_history=returns_df,  # optional: for correlation diagnostics
)

# Append to audit trail (append-only JSONL)
analyzer.record(diagnostics)

# Read latest record
latest = analyzer.get_latest()

# Human-readable summary
print(analyzer.format_summary(diagnostics))
```

## Output Format

Every rebalance cycle appends a JSONL record to `reports/r4_loop/portfolio_analytics.jsonl`:

```json
{
  "timestamp": "2026-09-01T11:34:31Z",
  "equity": 5000.00,
  "position_count": 8,
  "gross_exposure": 12400.00,
  "net_exposure": 3200.00,
  "gross_leverage": 2.48,
  "net_leverage": 0.64,
  "currency_exposure": {"USD": -8500, "EUR": 2100, "GBP": 1800},
  "currency_exposure_pct": {"USD": -1.70, "EUR": 0.42, "GBP": 0.36},
  "largest_currency_factor": "USD",
  "largest_currency_factor_pct": 1.70,
  "herfindahl_index": 0.189,
  "effective_positions": 5.3,
  "correlation_diagnostics": {
    "effective_bets": 4.6,
    "avg_pairwise_correlation": 0.038,
    "cluster_count": 2,
    "market_factor_fraction": 0.345
  },
  "counterfactuals": {
    "equal_weight": {"effective_positions": 8.0, "herfindahl": 0.125},
    "inverse_volatility": {"effective_positions": 5.0}
  }
}
```

## Phase 2 Governance

This module is frozen for Phase 2. The purpose is **observation**, not optimization.

> If the live data eventually tells us:
> "18 positions → 4.2 effective bets → 2 dominant currency factors → 3.1× gross leverage"
> then *that* becomes evidence for the Phase 3 portfolio-construction hypothesis.
> It is much stronger than us deciding today that "18 positions is too many" based on intuition.

## Phase 3 Roadmap

```
Phase 2 (current):
  Shadow analytics → observe → measure → understand → economic verdict

Phase 3 (if R4 produces interesting result):
  R4 baseline
    ├── Independent sizing (current)
    ├── Portfolio heat measurement
    ├── Inverse-volatility baseline
    ├── Risk parity
    ├── Factor-constrained allocation
    └── Only if evidence justifies: HRP / optimization
```
