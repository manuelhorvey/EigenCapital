# BASELINE SNAPSHOT — AUTO-GENERATED

Generated: 2026-06-20
Source: `configs/paper_trading.yaml`, `LIVE_CONTRACT.md`

---

## 1. SYSTEM CONFIG

| Parameter | Value |
|---|---|
| Capital | $100,000 |
| Position size | 0.95 |
| Retrain freq | annual |
| Retrain window | 5y |
| Drawdown limit | -0.15 |
| Data source | MT5 (yfinance fallback) |
| Ensemble | disabled portfolio-wide (base_weight=1.0; see ADR-026) |
| Governance layers | 11 + HealthMonitor (validity, feature stability, meta-label, macro narrative, liquidity, PSI drift, sell-only filter, equity cluster alarm, circuit breaker, portfolio drawdown, entry deviation, profit lock) |
| Decision pipeline stages | 19 stages (`DEFAULT_STAGES`: first-cycle suppression, bar-jump, store metadata, update MAE/MFE, resolve signal, risk-off, sell-only filter, spread gate, confidence gate, stability, hysteresis, meta-label advisory, regime bar counter, conviction gate, profit lock, manage position, build artifacts, route execution, poll deferred) |
| Position sizing guardrails | drawdown taper, per-position cap, risk-per-trade cap, leverage budget, backstop multiplier |
| Spread gate tiers | fx_major=10bps, fx_cross=20bps, indices=15bps, metals=20bps |
| Circuit breaker | max_consecutive_losses=7 (was 15) |
| Exit reasons | UPPERCASE canonical (FLIP, SL, TP, BREAKEVEN, EXPIRY, GATE_CLOSED, PORTFOLIO_CIRCUIT_BREAKER, SELL_ONLY_FILTER) |
| Cycle interval | 30s (configurable via QUANTFORGE_REFRESH_INTERVAL) |
| Schema migration | DB_SCHEMA_VERSION=2.0.0 (adds cycle_id, vol_spike, var_95) |

---

## 2. ASSET ALLOCATION

| Asset | Ticker | Allocation | sl_mult | tp_mult | max_depth |
|---|---|---|---|---|---|---|
| GC | GC=F | 7.0% | 1.00 | 4.00 | 2 |
| USDCHF | USDCHF=X | 4.0% | 0.85 | 3.00 | 4 |
| USDCAD | USDCAD=X | 2.5% | 2.50 | 2.03 | 5 |
| ES | ES=F | 7.0% | 2.00 | 5.50 | 2 |
| NQ | NQ=F | 7.0% | 2.50 | 5.00 | 2 |
| GBPCAD | GBPCAD=X | 5.0% | 2.50 | 2.50 | 2 |
| NZDCAD | NZDCAD=X | 5.0% | 2.50 | 4.00 | 2 |
| ^DJI | ^DJI | 4.0% | 0.50 | 4.00 | 4 |
| NZDUSD | NZDUSD=X | 2.5% | 2.50 | 1.50 | 5 |
| GBPAUD | GBPAUD=X | 5.0% | 1.00 | 2.00 | 3 |
| NZDCHF | NZDCHF=X | 7.0% | 1.00 | 4.00 | 2 |
| CADCHF | CADCHF=X | 5.0% | 1.00 | 4.00 | 2 |
| AUDUSD | AUDUSD=X | 4.0% | 1.50 | 4.00 | 2 |
| EURCHF | EURCHF=X | 5.0% | 1.00 | 3.00 | 4 |
| EURCAD | EURCAD=X | 2.0% | 1.00 | 1.00 | 3 |
| EURNZD | EURNZD=X | 3.0% | 1.50 | 2.50 | 3 |
| GBPCHF | GBPCHF=X | 3.0% | 1.00 | 2.00 | 2 |
| EURAUD | EURAUD=X | 1.0% | 0.54 | 1.77 | 2 |

**Removed 2026-06-20:** AUDNZD, EURUSD, AUDCHF, GBPNZD (directional instability). USDCAD/NZDUSD halved 5%→2.5%.

---

## 3. MODEL FILES

**Directory:** `paper_trading/models/` — 18 `.json` models (AUDCHF, EURUSD, AUDNZD, GBPNZD removed)

- `GC_model.json`
- `USDCHF_model.json`
- `USDCAD_model.json`
- `ES_model.json`
- `NQ_model.json`
- `GBPCAD_model.json`
- `NZDCAD_model.json`
- `DJI_model.json`
- `NZDUSD_model.json`
- `GBPAUD_model.json`
- `NZDCHF_model.json`
- `CADCHF_model.json`
- `AUDUSD_model.json`
- `EURCHF_model.json`
- `EURCAD_model.json`
- `EURNZD_model.json`
- `GBPCHF_model.json`
- `EURAUD_model.json`

---

## 4. EXECUTION GOVERNANCE

| Layer | State |
|---|---|
| Narrative | enabled |
| Liquidity | enabled |
| Regime geometry | per-asset (GREEN, YELLOW, RED) |
| Flip gate | enabled |
| Meta-labeling | enabled |
| PSI drift | enabled |
| Sell-only filter | enabled (11 assets: CADCHF, AUDUSD, ES, NQ, NZDCHF, EURAUD, ^DJI, USDCHF, EURCHF, NZDUSD, EURNZD) |
| Equity cluster alarm | enabled (ES/NQ/^DJI same-side detection, 60s throttle) |
| Circuit breaker | enabled (max_consecutive_losses=7) |
| HealthMonitor | enabled (Phase 3g: VaR, CVaR, vol, halt ratio) |
| RecoveryScheduler | enabled (exponential-backoff probe of halted actors) |
| Portfolio drawdown | enabled |
| Entry price deviation gate | enabled (max_entry_slippage_pct=2%) |
| Profit lock gate | enabled (profit_lock_threshold_pct=15%) |
| Spread gate | observe-only mode (720 cycles) |
| Bar-jump suppression | enabled (120 cycles) |
| Risk-off suppression | enabled (AUDUSD only — AUDCHF removed) |
| First-cycle suppression | enabled |
| Signal stability filter | enabled (stability_margin=0.15) |
| Signal hysteresis | enabled (2-of-3 agreement) |

---

## 5. OPTIMIZATIONS

| Optimization | Value |
|---|---|
| Truncate inference | auto |
| Batch HTTP | True |
| SQLite state | True (schema v2.0.0) |
| Vectorized labels | True |
| Async diagnostics | True |
| Regime conviction flip gate | enabled |
| Exit reason canonicalization | enabled (SQLite migration, UPPERCASE) |

---

## 6. LIVE_CONTRACT.md REFERENCE

For full contract details see [`LIVE_CONTRACT.md`](LIVE_CONTRACT.md).

Key invariants from the contract:
- XGBoost binary classifier with `.json` serialization
- Daily OHLCV from MT5 / yfinance
- Triple-barrier labeling with per-asset pt_sl
- Fixed-threshold signal strategy at 0.45
- 18 promoted assets with risk-parity weights
- Per-asset max_depth (2–5)
- Dynamic SL/TP with trailing stops and per-asset min_rr_ratio
- Ensemble disabled portfolio-wide (base_weight=1.0)
- Decision pipeline: 19 stages (first-cycle, bar-jump, store metadata, update MAE/MFE, resolve signal, risk-off, sell-only filter, spread gate, confidence gate, stability, hysteresis, meta-label advisory, regime bar counter, conviction gate, profit lock, manage position, build artifacts, route execution, poll deferred)
- Sell-only filter for 11 inverted-BUY assets
- HealthMonitor with VaR(95)/CVaR in Phase 3g
- Schema migration at DB_SCHEMA_VERSION=2.0.0
- Exit reasons canonicalized to UPPERCASE (including SELL_ONLY_FILTER)
- Independent paper/MT5 sizing chains

---

*This file documents the baseline system state at the time of generation. Update via `make snapshot`.*
