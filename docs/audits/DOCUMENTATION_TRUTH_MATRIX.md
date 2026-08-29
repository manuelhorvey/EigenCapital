# Documentation Truth Matrix

**Date:** 2026-08-29
**Status:** CURRENT

Every claim in documentation traced to its authoritative source. Code is the source of truth.

---

## README.md

| Claim | Actual Source | Verification | Status |
|-------|--------------|--------------|--------|
| R4 frozen momentum strategy | `strategies/trend/strategy.py` | Code | ✅ VERIFIED |
| Volatility-normalized signal | `strategies/trend/features.py` | Code | ✅ VERIFIED |
| Lookback 63 bars (~3 months daily) | `TrendConfig.lookback_period = 63` | Config | ✅ VERIFIED |
| Vol lookback 21 bars (~1 month) | `TrendConfig.volatility_lookback = 21` | Config | ✅ VERIFIED |
| Entry threshold ±1.0 | `TrendConfig.entry_threshold = 1.0` | Config | ✅ VERIFIED |
| Exit threshold 0.0 | `TrendConfig.exit_threshold = 0.0` | Config | ✅ VERIFIED |
| Risk target 10% annualized | `TrendConfig.risk_target = 0.10` | Config | ✅ VERIFIED |
| 24 symbols | `configs/production/config.toml` (31 total, 7 JPY excluded) | Config | ✅ VERIFIED |
| 19 max concurrent | `max_concurrent_positions = 19` | Config | ✅ VERIFIED |
| $5K position limit | `max_position_size = 5000.0` | Config | ✅ VERIFIED |
| $250 daily loss | `max_daily_loss = 250.0` | Config | ✅ VERIFIED |
| 10% max drawdown | `max_drawdown_pct = 10.0` | Config | ✅ VERIFIED |
| Equity floor $4,000 | `min_equity = 4000.0` | Config | ✅ VERIFIED |
| Phase 2 active | `docs/production/PHASE_STATUS.md` | Docs | ✅ VERIFIED |
| Dashboard read-only | `dashboard/api/routes/` — no POST/PUT/PATCH/DELETE | Code | ✅ VERIFIED |
| 20-40+ day holding periods | Observation-based claim | UNVERIFIED |
| 7 JPY crosses excluded | `configs/production/config.toml` — forex_excluded entries | Config | ✅ VERIFIED |
| Data Infrastructure layer | `core/market_schedule.py`, `core/data_quality.py`, `core/data_truth.py` | Code | ✅ VERIFIED |

---

## Strategy Description

| Claim | Actual Source | Status |
|-------|--------------|--------|
| Signal = cumulative_return / annual_vol | `features.py:compute_trend_signal()` | ✅ VERIFIED |
| Cumulative return = (end/start) - 1 | `features.py:compute_cumulative_return()` | ✅ VERIFIED |
| annual_vol = daily_vol × √252 | `features.py:compute_realized_volatility()` | ✅ VERIFIED |
| Target risk = abs(zscore) × 0.10 | `strategy.py:130` | ✅ VERIFIED |
| Runs on daily bars (D1) | `r4_rebalance_loop.py:277` — `TIMEFRAME_D1` | ✅ VERIFIED |
| Hourly rebalance cadence | `scripts/r4_rebalance_loop.py --interval 3600` | ✅ VERIFIED |

---

## Risk Controls

| Control | Limit | Source | Status |
|---------|-------|--------|--------|
| Position notional | ≤ $5,000 | `config.toml` | ✅ VERIFIED |
| Daily loss | ≤ $250 | `config.toml` | ✅ VERIFIED |
| Drawdown | ≤ 10% | `config.toml` | ✅ VERIFIED |
| Equity floor | ≥ $4,000 | `config.toml` | ✅ VERIFIED |
| Max concurrent | ≤ 19 | `config.toml` | ✅ VERIFIED |
| Catastrophic SL | 2× ATR14 or 1% floor | `live/risk.py` | ✅ VERIFIED |
| Foreign quarantine | 0 foreign positions | `live/position_attribution.py` | ✅ VERIFIED |
| Fingerprint enforcement | 5 components | `production_qual/fingerprint_verifier.py` | ✅ VERIFIED |
| REDUCED | Shadow-only | `live/risk_enforcement.py:529` | ✅ VERIFIED |

---

## Dashboard

| Claim | Source | Status |
|-------|--------|--------|
| Read-only | No POST/PUT/PATCH/DELETE routes | ✅ VERIFIED |
| 8 pages | `dashboard/src/pages/` — 8 .tsx files | ✅ VERIFIED |
| WebSocket live streaming | `dashboard/src/hooks/useLiveStream.ts` | ✅ VERIFIED |
| HealthMatrix 6 dimensions | `dashboard/src/components/ui/HealthMatrix.tsx` | ✅ VERIFIED |
| CORS restricted | `dashboard/api/app.py` — localhost origins | ✅ VERIFIED |
| GET-only methods | `allow_methods=["GET"]` in CORS config | ✅ VERIFIED |

---

## Data Infrastructure

| Component | Source | Status |
|-----------|--------|--------|
| MarketSchedule | `core/market_schedule.py` | ✅ VERIFIED |
| DataQuality | `core/data_quality.py` | ✅ VERIFIED |
| DataTruth | `core/data_truth.py` | ✅ VERIFIED |
| MarketDataBridge | `core/data_quality.py:MarketDataBridge` | ✅ VERIFIED |
| NoSilentDegradation | `core/no_silent_degradation.py` | ✅ VERIFIED |
| 25 instruments configured | `configs/market_schedules/default.toml` | ✅ VERIFIED |
| BTCUSD = CONTINUOUS_24_7 | `default.toml` | ✅ VERIFIED |
| FX = WEEKDAY | `default.toml` | ✅ VERIFIED |

---

## Incorrect Claims Found & Fixed

| Document | Incorrect Claim | Corrected To | Date |
|----------|----------------|--------------|------|
| README.md | "volatility-gated regimes" | Removed — no regime gate in code | 2026-08-29 |
| README.md | "Signal clips weights to ±20%" | Removed — no weight clipping in code | 2026-08-29 |
| README.md | "Correlation monitoring (rolling 20/60/120-day)" | "Asset-class concentration monitoring" | 2026-08-29 |
| README.md | "Regime gate (no trade when vol > median)" | Removed — no regime gate in code | 2026-08-29 |

---

## Terminology

| Term | Definition | Source |
|------|-----------|--------|
| Volatility-normalized momentum score | Cumulative return / annualized volatility. Conceptually Z-score-like but not a strict statistical Z-score. | `features.py` |
| REDUCED | Shadow-only soft constraint. Calculates hypothetical reduced position sizes. Never applied to live trading. | `risk_enforcement.py` |
| Evidence maturity (E0-E6) | 7 levels of trade lifecycle observation, from signal to portfolio outcomes. | `production_qual/evidence_maturity.py` |
| MarketSchedule | Authoritative trading calendar per instrument. Determines open/closed/maintenance state. | `core/market_schedule.py` |
| ExpectedDataState | Whether missing data is expected (market closed) or unexpected (market open, no data). | `core/data_quality.py` |
