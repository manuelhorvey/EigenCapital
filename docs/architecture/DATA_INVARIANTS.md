# EigenCapital Data Invariants

## Canonical Chain of Truth

Every data value in EigenCapital must follow this chain:

```
MarketSchedule
      ↓
"Should data exist?"
      ↓
MarketDataBridge
      ↓
DataQuality
      ↓
"Is the data trustworthy?"
      ↓
DataTruth
      ↓
"What exactly do we know?"
      ↓
Risk / Health / Authorization
```

## Architectural Invariants

### 1. Single Source of Truth

> **There must be exactly one authoritative source for market availability, one canonical mechanism for data-quality assessment, and one canonical representation of data truth.**

- `MarketSchedule` is the single source for market availability
- `DataQualityAssessor` is the single mechanism for data quality
- `TruthfulValue` / `TruthLevel` is the single representation of data truth
- Downstream components must consume these abstractions rather than reimplementing their own

### 2. No Silent Degradation

> **UNKNOWN, MISSING, STALE, UNAVAILABLE, CORRUPT must NEVER silently become 0, NORMAL, SAFE, VERIFIED.**

Forbidden patterns:
```python
equity = account.equity or 0          # ❌ None → 0
price = response.price or 0           # ❌ None → 0
status = data.get("status") or "OK"   # ❌ None → "OK"
```

Required patterns:
```python
equity = guard_not_none(account.equity, "equity")
# or
if account.equity is None:
    show("No equity data")
else:
    show(account.equity)
```

### 3. Market State Explains Data Absence

> **When the market is closed or in maintenance, missing data is EXPECTED. When the market is open, missing data is a PROBLEM.**

```
Market CLOSED + No tick  → EXPECTED_MISSING → No alert, no degradation
Market OPEN   + No tick  → UNEXPECTED_MISSING → Alert, quality POOR
Market OPEN   + Stale    → UNEXPECTED_STALE → Risk observation
```

### 4. Quality Scores Are Diagnostic, Not Authoritative

> **A quality score of 84 does not authorize trading. Only explicit predicates authorize trading.**

```python
# ❌ Wrong — score-based authorization
if quality.score > 80:
    allow_trading()

# ✅ Correct — predicate-based authorization
if (market == OPEN
    and freshness == PASS
    and completeness == PASS
    and broker == CONNECTED):
    allow_trading()
```

### 5. Risk Monitoring Never Stops

> **Position monitoring, risk observation, and health assessment continue even when the market is closed.**

Market closure suppresses signal evaluation and execution, but NOT:
- Position monitoring (MAE/MFE tracking)
- Risk observation (stale data detection)
- Health monitoring (watchdog, broker connectivity)
- Reconciliation (state consistency)
- Evidence collection (lifecycle ledger)

### 6. No Duplicate Interpretations

> **There must be exactly one interpretation of market state, data quality, and data truth across the entire platform.**

Forbidden:
```python
# In dashboard:
if dt.weekday() >= 5:
    data["freshness"] = "UNKNOWN"

# In risk engine:
if is_weekend():
    suppress_trading()
```

Required:
```python
# All components use the same abstraction:
schedule = get_market_schedule(instrument)
state = MarketDataBridge(schedule).assess(...)
```

## Module Responsibilities

| Module | Responsibility | Consumed By |
|--------|---------------|-------------|
| `MarketSchedule` | Market availability (open/closed/maintenance) | MarketDataBridge, risk, execution |
| `DataQualityAssessor` | Data quality dimensions (freshness, completeness, spread) | MarketDataBridge, dashboard |
| `TruthfulValue` / `TruthRegistry` | Data truth level (authoritative/derived/estimated) | Dashboard, risk, health |
| `MarketDataBridge` | Connects schedule to quality to truth | Dashboard, risk observation |
| `no_silent_degradation` | Prevents None→0, missing→default | All components |
| `QualityGrade` | Overall quality assessment | Dashboard, alerts |

## Integration Rule

Every component that displays or acts on data must:

1. Use `MarketDataBridge` for market-data quality decisions
2. Use `TruthfulValue` for all displayed values
3. Use `guard_*` functions for defensive value access
4. Never implement its own staleness/freshness logic
5. Never use `or 0`, `or ""`, `or "UNKNOWN"` as fallbacks
