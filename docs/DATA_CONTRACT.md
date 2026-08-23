# EigenCapital Data Contract

The data constitution. Every data pipeline in EigenCapital must conform to this document.

---

## What EigenCapital Considers a Valid Bar

A valid bar satisfies ALL of the following:

1. **Timestamp is ISO-8601 UTC** with `Z` suffix (e.g., `2024-03-15T09:35:00Z`)
2. **`bar_start_utc < bar_end_utc`** (chronological order)
3. **`timestamp_utc == bar_end_utc`** (interval-end convention)
4. **All OHLC prices are finite, positive floats**
5. **`high >= max(open, close)`** and **`low <= min(open, close)`**
6. **`volume >= 0`**
7. **`instrument_id` is non-empty** and matches a known instrument
8. **`bar_interval` is a recognized interval** (e.g., `1m`, `5m`, `1d`)

---

## Data Quality Classification

### VALID

- All structural invariants satisfied
- No anomalous patterns detected
- Data passes all validation checks

### WARNING

- Data passes structural checks but exhibits unusual patterns
- Extreme price movement (legitimate but noteworthy)
- Volume spike (may indicate news event)
- Flatlined price (may indicate halted trading)
- Missing data gaps detected
- **WARNING data CAN be used in research** but must be flagged in the DecisionSnapshot

### INVALID

- Structural invariant violated (e.g., `high < low`)
- Missing required fields
- Negative prices or negative volume
- Duplicate timestamps within same instrument/interval
- Out-of-order timestamps
- Overlapping bar intervals
- **INVALID data MUST NOT enter any canonical pipeline**

### STALE

- Data timestamp is significantly behind current time
- For intraday data: more than 1 bar interval behind expected
- For daily data: more than 1 day behind expected
- **STALE data MAY be used for analysis but MUST NOT trigger live execution**

---

## Timestamp Semantics

- **All timestamps are UTC** (never naive, never timezone-offset)
- Format: ISO-8601 with `Z` suffix: `2024-03-15T09:35:00Z`
- `timestamp_utc` equals `bar_end_utc` (interval-end convention)
- `bar_start_utc < bar_end_utc` (strict ordering)
- `bar_end_utc - bar_start_utc` must equal the declared `bar_interval`

---

## Session Semantics

- `session`: `OPEN`, `CLOSED`, or `AUCTION`
- Bars during `CLOSED` session are informational only, not actionable
- Bars during `AUCTION` session have incomplete data (pre/opening auction)

---

## Volume Semantics by Asset Class

### Futures (EQUITY_FUTURE)

- Volume is contract count
- Zero volume is valid (no trades in interval)
- Negative volume is always invalid
- Volume spikes > 10x average are flagged as WARNING

### FX (FX)

- Volume may be unavailable (provider-dependent)
- When unavailable, volume is `None`
- Zero volume is valid

### Equity (EQUITY)

- Volume is share count
- Zero volume may indicate halted trading
- Negative volume is always invalid

### Crypto (CRYPTO)

- Volume is base-asset units
- Available 24/7 (no session boundaries)
- Zero volume is valid (thin markets)

---

## Corporate Action Treatment

- Adjusted prices are preferred when available
- Unadjusted prices must be flagged with `data_version` or `adjustment_type` metadata
- Splits, dividends, and mergers must not create artificial price jumps

---

## Futures Roll Treatment

- Rolled contracts generate a new `instrument_id` (e.g., `ES_2403` → `ES_2406`)
- The parent instrument (e.g., `ES`) is a composite of its rolls
- Roll dates are determined by expiry rules, not price continuity
- No implicit rollover in normalization

---

## FX Convention

- Standard convention: `BASE_QUOTE` (e.g., `EURUSD` = 1 EUR in USD)
- `tick_size` in pips (typically 0.0001 for major pairs)
- `tick_value` per standard lot
- No pip convention ambiguity — always explicit in metadata

---

## Crypto 24/7 Treatment

- No session boundaries
- Trading calendar is `24x7x365`
- Bars are continuous across midnight UTC
- `session` is always `OPEN`

---

## Dataset Versioning

Every normalized dataset MUST have:

| Field | Description |
|-------|-------------|
| `dataset_id` | Unique identifier (e.g., `equities_daily_v1`) |
| `dataset_version` | Semantic version |
| `source` | Data provider identifier |
| `instrument_universe` | List of instrument_ids in dataset |
| `bar_interval` | Resolution of bars |
| `start_date` | First bar timestamp (UTC) |
| `end_date` | Last bar timestamp (UTC) |
| `record_count` | Total number of bars |
| `validation_stats` | Counts of VALID/WARNING/INVALID/STALE |
| `created_at` | ISO-8601 UTC creation timestamp |
| `content_hash` | SHA-256 of normalized content |

---

## Provider Precedence

When multiple providers supply data for the same instrument:

1. Higher-quality provider wins (fewer INVALID/STALE results)
2. If quality is equal, prefer provider with more fields populated
3. Provider preference can be overridden per-instrument in configuration
4. **Never silently merge** data from multiple providers without explicit configuration

---

## Data Correction Policy

### Permitted Corrections

- **Timezone normalization**: Convert to UTC (with original preserved in metadata)
- **Column renaming**: Map provider-specific names to canonical names
- **Type coercion**: Convert strings to floats where semantically equivalent
- **Null handling**: Preserve `None` for genuinely missing data

### Prohibited Corrections

- **Swapping high/low** when `high < low`
- **Imputing missing prices** from neighboring bars
- **Rounding prices** to hide imprecision
- **Filling volume gaps** with zeros or averages
- **Adjusting prices** without explicit version marker

---

## Deterministic Normalization

Given identical raw input, normalization MUST produce identical output:

```
hash(normalize(raw_A)) == hash(normalize(raw_A))  # always true
hash(normalize(raw_A)) == hash(normalize(raw_B))  # only if raw_A == raw_B
```

This is enforced through:
- Sorted dict keys in serialization
- Explicit null handling (not omitted)
- ISO-8601 UTC timestamps
- Deterministic hash via `canonical_serialization.py`
