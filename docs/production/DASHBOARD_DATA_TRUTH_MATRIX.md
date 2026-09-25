# Dashboard Data Truth Matrix

> Every value displayed on the EigenCapital dashboard must be traceable to a single authoritative source.
> The dashboard is a **read-only observer** — it never creates, modifies, or fabricates trading state.

**Regenerated:** 2026-09-25 (full re-audit; supersedes the 2026-08-29 version — several "known issues" listed there were fixed in code and are documented as resolved below)
**Governing contract:** [`DASHBOARD_CONTRACT.md`](DASHBOARD_CONTRACT.md) (truthfulness T1–T5, single-writer §4, lineage §3)
**Verification at regeneration:** dashboard tests 112 passed · mypy clean · tsc clean · oxlint clean
**Architecture:** `Domain/Live State → DashboardStateService → Pydantic DTO → FastAPI → React Query → Component → Operator`

---

## Freshness Semantics

| Freshness | Meaning | Age | Visual |
|-----------|---------|-----|--------|
| `LIVE` | Current, authoritative | < 30s | Green indicator |
| `STALE` | Valid but aging | 30s–5min | Yellow indicator, "(stale)" suffix |
| `UNKNOWN` | > 5min old, missing, or no data | > 5min or absent | Muted, "No data" / "Unavailable" |

---

## Account State

| Dashboard Field | Frontend Component | API Endpoint | DTO Field | Backend Service Method | Authoritative Source | Transformation | Units | Precision | Freshness | Fallback | Security |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Equity | Overview → MetricCard | `GET /portfolio/account` | `AccountDTO.equity` | `get_account_state()` | `MT5 account_info().equity` | None | USD | 2dp (formatted) | LIVE/STALE/UNKNOWN | 0 + `UNKNOWN` | Read-only |
| Balance | Overview → MetricCard | `GET /portfolio/account` | `AccountDTO.balance` | `get_account_state()` | `MT5 account_info().balance` | None | USD | 2dp | LIVE/STALE/UNKNOWN | 0 + `UNKNOWN` | Read-only |
| Free Margin | Positions → Metric | `GET /portfolio/account` | `AccountDTO.free_margin` | `get_account_state()` | `MT5 account_info().margin_free` | None | USD | 2dp | LIVE/STALE/UNKNOWN | 0 | Read-only |
| Margin Used | Overview → MetricCard | `GET /portfolio/account` | `AccountDTO.margin_used` | `get_account_state()` | `MT5 account_info().margin` | None | USD | 2dp | LIVE/STALE/UNKNOWN | 0 | Read-only |
| Margin Utilization | Overview → MetricCard | `GET /portfolio/account` | `AccountDTO.margin_utilization` | `get_account_state()` | Derived: `1 - (margin_free / equity)` | Computation | ratio (0–1) | 1dp (displayed as %) | LIVE/STALE/UNKNOWN | 0 | Read-only |
| Drawdown % | Overview → MetricCard | `GET /portfolio/account` | `AccountDTO.drawdown_pct` | `get_account_state()` | Derived: `(hwm - equity) / hwm` from RiskEnvelope | Computation | % | 2dp | LIVE/STALE/UNKNOWN | 0 | Read-only |
| Equity High Water | Overview → MetricCard | `GET /portfolio/account` | `AccountDTO.equity_high_water` | `get_account_state()` | Derived: `max(equity, t0_equity)` | Computation | USD | 2dp | LIVE/STALE/UNKNOWN | 0 | Read-only |
| Daily P&L | Overview → MetricCard | `GET /portfolio/account` | `AccountDTO.daily_pnl` | `get_account_state()` | **⚠ HARDCODED to 0** — not computed live | None | USD | 2dp | LIVE/STALE/UNKNOWN | 0 | Read-only |
| Daily Loss Remaining | Overview → MetricCard | `GET /portfolio/account` | `AccountDTO.daily_loss_remaining` | `get_account_state()` | `RiskEnvelope.max_daily_loss` | None | USD | 2dp | LIVE/STALE/UNKNOWN | 250 (hardcoded default in DTO) | Read-only |
| Unrealized P&L | Overview → MetricCard | `GET /portfolio/account` | `AccountDTO.unrealized_pnl` | `get_account_state()` | **⚠ HARDCODED to 0** — not computed live | None | USD | 2dp | LIVE/STALE/UNKNOWN | 0 | Read-only |

### ✅ Resolved (2026-09-25) — Account State

The 2026-08-29 issues below were fixed in code and verified:

1. ~~`daily_pnl` always returns 0~~ — now computed from `daily_baseline.json` equity
2. ~~`unrealized_pnl` always returns 0~~ — now summed from live MT5 position profits
3. ~~`drawdown` field always returns 0~~ — now computed against the true HWM
4. ~~`equity_high_water` = current equity~~ — now `max(equity, t0_equity, runtime_state.peak_equity)`
5. `daily_loss_remaining` is supplied by `RiskEnvelope`; the DTO schema default of 250 remains only as a last-resort fallback (P2 backlog: remove the magic default)

---

## Positions

| Dashboard Field | Frontend Component | API Endpoint | DTO Field | Backend Service Method | Authoritative Source | Transformation | Units | Precision | Freshness | Fallback |
|---|---|---|---|---|---|---|---|---|---|---|
| Symbol | Positions → table/card | `GET /portfolio/positions` | `PositionDTO.symbol` | `get_positions()` | `MT5 position.symbol` | None | string | — | LIVE | Empty list |
| Direction | Positions → StatusBadge | `GET /portfolio/positions` | `PositionDTO.direction` | `get_positions()` | `MT5 position.type` → "BUY"/"SELL" | Mapping: 0→BUY, else→SELL | enum | — | LIVE | Empty list |
| Size | Positions → table/card | `GET /portfolio/positions` | `PositionDTO.size` | `get_positions()` | `MT5 position.volume` | None | lots | 2dp | LIVE | Empty list |
| Entry Price | Positions → table/card | `GET /portfolio/positions` | `PositionDTO.entry_price` | `get_positions()` | `MT5 position.price_open` | None | price | 5dp | LIVE | Empty list |
| Current Price | Positions → table/card | `GET /portfolio/positions` | `PositionDTO.current_price` | `get_positions()` | `MT5 position.price_current` | None | price | 5dp | LIVE | Empty list |
| Unrealized P&L | Positions → table/card | `GET /portfolio/positions` | `PositionDTO.unrealized_pnl` | `get_positions()` | `MT5 position.profit` | None | USD | 2dp | LIVE | Empty list |
| P&L % | Positions → table/card | `GET /portfolio/positions` | `PositionDTO.unrealized_pnl_pct` | `get_positions()` | Derived: direction-aware price change % | Computation | ratio | 4dp | LIVE | Empty list |
| Stop Loss | Positions → table/card | `GET /portfolio/positions` | `PositionDTO.stop_loss` | `get_positions()` | `MT5 position.sl` (0→None) | None | price | 5dp | LIVE | None |
| Distance to SL | Positions → table/card | `GET /portfolio/positions` | `PositionDTO.distance_to_sl` | `get_positions()` | Derived: `abs(current - sl)` | Computation | price | 5dp | LIVE | None |
| MAE | Positions → detail | `GET /portfolio/positions` | `PositionDTO.mae` | `get_positions()` | `reports/r4_loop/position_excursion.json` (RiskObserver excursion tracker) | None | pct | — | LIVE when position present | None |
| MFE | Positions → detail | `GET /portfolio/positions` | `PositionDTO.mfe` | `get_positions()` | `position_excursion.json` (as above) | None | pct | — | LIVE when position present | None |
| Holding Time | Positions → table/card | `GET /portfolio/positions` | `PositionDTO.holding_time` | `get_positions()` | Derived: `now - entry_time` | Formatting | string ("5m", "3h") | — | LIVE | None |
| Risk State | Positions → StatusDot | `GET /portfolio/positions` | `PositionDTO.risk_state` | `get_positions()` | Derived: NORMAL / WARNING (>1% adverse or no SL) / CRITICAL (>2% adverse) | Computation | enum | — | LIVE | "NORMAL" only when protected and ≤1% |
| Protected | Positions → StatusDot | `GET /portfolio/positions` | `PositionDTO.protected` | `get_positions()` | Derived: `MT5 position.sl > 0` | Computation | bool | — | LIVE | False |
| Attribution State | Positions → detail | `GET /portfolio/positions` | `PositionDTO.attribution_state` | `get_positions()` | Position attribution system (not yet linked — displayed as "No data", never inferred) | None | str | — | — | None |

### ✅ Resolved (2026-09-25) — Positions

1. ~~`risk_state` always "NORMAL"~~ — now derived: NORMAL / WARNING (>1% adverse move or no SL) / CRITICAL (>2% adverse move)
2. ~~`mae`/`mfe` always None~~ — now read from `reports/r4_loop/position_excursion.json` (RiskObserver excursion tracker)
3. `attribution_state` remains None in the position adapter (attribution system not yet linked) — displayed as "No data", never inferred

**Lifecycle display — removed (contract T1).** The position detail previously rendered a hardcoded Signal→Order→Fill→Position→Risk strip as if complete for every ticket. Per-ticket event correlation is not backend-backed, so the strip was removed (2026-09-25) and returns only with real per-event data. Signal → Target → Risk decision → Order → Fill → Position remain distinct and are not conflated in the UI.

---

## Risk

| Dashboard Field | Frontend Component | API Endpoint | DTO Field | Backend Service Method | Authoritative Source | Freshness | Fallback |
|---|---|---|---|---|---|---|---|
| Overall Level | Risk → StatusBadge | `GET /risk` | `RiskStateDTO.overall_level` | `get_risk_state()` | `RiskObserver.overall_level` or persisted `risk_state.json` | LIVE/STALE/UNKNOWN | "UNKNOWN" |
| Observations (×14) | Risk → dimension groups | `GET /risk` | `RiskStateDTO.observations[]` | `get_risk_state()` | `RiskObserver.observations` | LIVE/STALE/UNKNOWN | Empty list |
| Any Critical | Risk → header | `GET /risk` | `RiskStateDTO.any_critical` | `get_risk_state()` | Derived from observations | LIVE/STALE/UNKNOWN | False |
| Any Warning | Risk → header | `GET /risk` | `RiskStateDTO.any_warning` | `get_risk_state()` | Derived from observations | LIVE/STALE/UNKNOWN | False |
| Critical Dimensions | Risk → header | `GET /risk` | `RiskStateDTO.critical_dimensions` | `get_risk_state()` | Derived from observations | LIVE/STALE/UNKNOWN | Empty list |
| Warning Dimensions | Risk → header | `GET /risk` | `RiskStateDTO.warning_dimensions` | `get_risk_state()` | Derived from observations | LIVE/STALE/UNKNOWN | Empty list |
| Risk Envelope | Risk → envelope panel | `GET /risk/envelope` | `RiskEnvelopeDTO.*` | Route: direct import | `RiskEnvelope.from_config()` | Static (config) | HTTP 503 |

### Risk Observation Dimensions

| Dimension | API Dimension Name | Source |
|---|---|---|
| Drawdown | `drawdown` | RiskObserver from equity vs HWM |
| Daily Loss | `daily_loss` | RiskObserver from daily P&L |
| Loss Velocity | `loss_velocity` | RiskObserver rate-of-change |
| Equity Floor | `equity_floor` | RiskObserver vs min_equity |
| Gross Exposure | `gross_exposure` | RiskObserver from position notionals |
| Net Exposure | `net_exposure` | RiskObserver from position notionals |
| Concentration | `concentration` | RiskObserver max single position |
| Position Count | `position_count` | RiskObserver count |
| Sector Breakdown | `sector_breakdown` | RiskObserver sector analysis |
| Margin Utilization | `margin_utilization` | RiskObserver from margin usage |
| SL Protection | `sl_protection` | RiskObserver SL coverage |
| Stale Data | `stale_data` | RiskObserver data age |
| Slippage | `slippage` | RiskObserver execution quality |
| VaR Estimate | `var_estimate` | RiskObserver VaR model |

---

## Health

| Dashboard Field | Frontend Component | API Endpoint | DTO Field | Backend Service Method | Authoritative Source | Freshness | Fallback |
|---|---|---|---|---|---|---|---|
| Overall State | Overview → banner | `GET /health` | `SystemHealthDTO.overall_state` | `get_system_health()` | Derived from 6 dimensions (below) | LIVE/STALE/UNKNOWN | "UNKNOWN" |
| Trading Authorization | Overview → banner | `GET /health` | `SystemHealthDTO.trading_authorization` | `get_system_health()` | Derived: HALTED/BLOCKED/DEGRADED/alive | LIVE/STALE/UNKNOWN | "UNKNOWN" |
| Dimensions (6) | Overview → HealthMatrix | `GET /health` | `SystemHealthDTO.dimensions[]` | `get_system_health()` | `supervisor`, `broker`, `risk_envelope`, `reconciliation`, `build`, `evidence` — each from its authoritative source | LIVE/STALE/UNKNOWN | Empty list |
| Blocking Dimensions | Overview → gate strip | `GET /health` | `SystemHealthDTO.blocking_dimensions` | `get_system_health()` | Dimensions in non-HEALTHY blocking state | LIVE/STALE/UNKNOWN | Empty list |
| Authorization Status | System → StatusDot | `GET /health/authorization` | `TradingAuthorizationDTO.status` | Route | Derived from health state | LIVE | "UNKNOWN" |
| Fingerprint Status | System → banner | `GET /health/authorization` | `TradingAuthorizationDTO.fingerprint_status` | Route | `get_build_identity().verified` — real verification, not hardcoded | LIVE | "UNKNOWN" |
| Watchdog State | System → StatusDot | `GET /health/watchdog` | `WatchdogDTO.state` | Route | Derived from authorization state | LIVE | "UNKNOWN" |

### ✅ Resolved (2026-09-25) — Health

1. ~~`dimensions` always empty~~ — six dimensions now populated (supervisor / broker / risk_envelope / reconciliation / build / evidence)
2. ~~`fingerprint_status` always "VERIFIED"~~ — now read from `get_build_identity().verified`
3. ~~Binary alive/dead model~~ — dimension states are HEALTHY/DEGRADED/BLOCKED/CONTAINED/HALTED (contract-tested); the Overview gate strip maps each chip to its actual dimension, and missing dimension data renders as a neutral unknown chip, not a green check (contract T2/T3)

---

## Reconciliation

| Dashboard Field | Frontend Component | API Endpoint | DTO Field | Backend Service Method | Authoritative Source | Freshness | Fallback |
|---|---|---|---|---|---|---|---|
| Overall Status | Recon → StatusBadge | `GET /reconciliation` | `ReconciliationStatusDTO.overall_status` | `get_reconciliation_status()` | `reconciliation_state.json` or derived from positions | LIVE/STALE/UNKNOWN | "NO_DATA" |
| Checks Performed | Recon → Metric | `GET /reconciliation` | `ReconciliationStatusDTO.checks_performed` | `get_reconciliation_status()` | Derived: total positions | LIVE/STALE/UNKNOWN | 0 |
| Checks Passed | Recon → Metric | `GET /reconciliation` | `ReconciliationStatusDTO.checks_passed` | `get_reconciliation_status()` | Derived: protected count | LIVE/STALE/UNKNOWN | 0 |
| Missing Fills | Recon → Metric | `GET /reconciliation` | `ReconciliationStatusDTO.missing_fills` | `get_reconciliation_status()` | **⚠ Always 0** — not checked | LIVE/STALE/UNKNOWN | 0 |
| Foreign Positions | Recon → Metric | `GET /reconciliation` | `ReconciliationStatusDTO.foreign_positions` | `get_reconciliation_status()` | Derived: unprotected positions | LIVE/STALE/UNKNOWN | 0 |
| Stale Positions | Recon → Metric | `GET /reconciliation` | `ReconciliationStatusDTO.stale_positions` | `get_reconciliation_status()` | **⚠ Always 0** — not checked | LIVE/STALE/UNKNOWN | 0 |
| Duplicate Orders | Recon → data | `GET /reconciliation` | `ReconciliationStatusDTO.duplicate_orders` | `get_reconciliation_status()` | **⚠ Always 0** — not checked | LIVE/STALE/UNKNOWN | 0 |

### ⚠ Known Limitations — Reconciliation

1. **Simplified fallback model** — when `reconciliation_state.json` (engine-written) is absent, status is derived from SL presence; labeled `NO_DATA` when nothing can be derived
2. **`missing_fills`, `stale_positions`, `duplicate_orders`** come from the engine file; the dashboard fallback reports 0 for these only alongside the `NO_DATA`/derived status, never presented as engine-verified values
3. **Single writer (contract §4):** the dashboard no longer persists `reconciliation_state.json` — derived fallbacks are in memory only (2026-09-25)

---

## Evidence & Qualification

| Dashboard Field | Frontend Component | API Endpoint | DTO Field | Backend Service Method | Authoritative Source | Freshness | Fallback |
|---|---|---|---|---|---|---|---|
| Campaign ID | Evidence → header | `GET /evidence/qualification` | `QualificationStatusDTO.campaign_id` | `get_qualification_status()` | `qualification_status.json` or T0 snapshots | LIVE/STALE/UNKNOWN | "" |
| Overall Status | Evidence → banner | `GET /evidence/qualification` | `QualificationStatusDTO.overall_status` | `get_qualification_status()` | Derived from evidence count | LIVE/STALE/UNKNOWN | "UNKNOWN" |
| Evidence Insufficient | Evidence → badge | `GET /evidence/qualification` | `QualificationStatusDTO.evidence_insufficient` | `get_qualification_status()` | Derived: total < 30 | LIVE/STALE/UNKNOWN | True |
| E0–E6 Counts | Evidence → maturity grid | `GET /evidence/qualification` | `EvidenceMaturityDTO.eN_count` | `get_qualification_status()` | Evidence directory file counts | LIVE/STALE/UNKNOWN | 0 |
| Total Trades | Evidence → header | `GET /evidence/qualification` | `EvidenceMaturityDTO.total_trades` | `get_qualification_status()` | Evidence directory file count | LIVE/STALE/UNKNOWN | 0 |
| Observation Days | Evidence → maturity | `GET /evidence/qualification` | `EvidenceMaturityDTO.observation_days` | `get_qualification_status()` | Evidence snapshots JSONL dates | LIVE/STALE/UNKNOWN | 0 |
| Qualification Gates | Evidence → gate list | `GET /evidence/qualification` | `QualificationStatusDTO.gates[]` | `get_qualification_status()` | Derived from counts vs thresholds | LIVE/STALE/UNKNOWN | Empty list |
| Shadow REDUCED | Evidence → purple panel | `GET /evidence/shadow-reduced` | `ShadowReducedDTO.*` | `get_shadow_reduced()` | `shadow_reduced.json` | LIVE/STALE/UNKNOWN | All zeros/nulls |

---

## Alerts

| Dashboard Field | Frontend Component | API Endpoint | DTO Field | Backend Service Method | Authoritative Source | Freshness | Fallback |
|---|---|---|---|---|---|---|---|
| Alert List | Alerts → panels | `GET /alerts` | `AlertDTO[]` | `get_recent_alerts()` | `alerts.jsonl` + `monitor.jsonl` | LIVE | Empty list |
| Severity | Alerts → StatusDot | `GET /alerts` | `AlertDTO.severity` | `get_recent_alerts()` | Source file `severity` field | LIVE | "INFO" |
| Category | Alerts → badge | `GET /alerts` | `AlertDTO.category` | `get_recent_alerts()` | Source file `category` field | LIVE | "SYSTEM" |
| Message | Alerts → text | `GET /alerts` | `AlertDTO.message` | `get_recent_alerts()` | Source file `message` field | LIVE | "Alert" |
| Consecutive Count | Alerts → text | `GET /alerts` | `AlertDTO.consecutive_count` | `get_recent_alerts()` | Source file `consecutive_count` | LIVE | 1 |

**Ordering (fixed 2026-09-25, audit F-03):** alerts are sorted newest-first and the **newest** `limit` items are returned (previously `[-limit:]` after the descending sort returned the oldest slice). Regression-tested in `tests/unit/dashboard/test_p1_sync_fixes.py`.

---

## System / Build

| Dashboard Field | Frontend Component | API Endpoint | DTO Field | Backend Service Method | Authoritative Source | Freshness | Fallback |
|---|---|---|---|---|---|---|---|
| Git HEAD | System → build panel | `GET /system/build` | `BuildIdentityDTO.git_head` | `get_build_identity()` | `compute_build_identity()` | LIVE (static) | "" |
| Build ID | System → build panel | `GET /system/build` | `BuildIdentityDTO.build_id` | `get_build_identity()` | `compute_build_identity()` | LIVE (static) | "" |
| Verified | System → banner | `GET /system/build` | `BuildIdentityDTO.verified` | `get_build_identity()` | `identity.all_verified` | LIVE (static) | False |
| Drift Detected | System → banner | `GET /system/build` | `BuildIdentityDTO.drift_detected` | `get_build_identity()` | `not identity.all_verified` | LIVE (static) | True |
| Manifest Identity | System → build panel | `GET /system/build` | `BuildIdentityDTO.manifest_identity` | `get_build_identity()` | `compute_build_identity()` | LIVE (static) | "" |
| Config Fingerprint | System → build panel | `GET /system/build` | `BuildIdentityDTO.config_fingerprint` | `get_build_identity()` | `compute_build_identity()` | LIVE (static) | "" |
| Dashboard Version | System → build panel | `GET /system/info` | `SystemInfo.dashboard_version` | Route | Hardcoded `"0.1.0"` | Static | "0.1.0" |
| Read-Only | System → guarantees | `GET /system/info` | `SystemInfo.read_only` | Route | Hardcoded `True` | Static | True |

---

## Events

| Dashboard Field | Frontend Component | API Endpoint | DTO Field | Backend Service Method | Authoritative Source | Freshness | Fallback |
|---|---|---|---|---|---|---|---|
| Event Type | Events → badge | `GET /evidence/events` | `EventDTO.event_type` | `get_recent_events()` | `decisions.jsonl → event/type` | LIVE | "UNKNOWN" |
| Timestamp | Events → text | `GET /evidence/events` | `EventDTO.timestamp` | `get_recent_events()` | `decisions.jsonl → timestamp` | LIVE | `datetime.now()` |
| Symbol | Events → text | `GET /evidence/events` | `EventDTO.symbol` | `get_recent_events()` | `decisions.jsonl → symbol` | LIVE | None |
| Correlation ID | Events → copy button | `GET /evidence/events` | `EventDTO.correlation_id` | `get_recent_events()` | `decisions.jsonl → correlation_id` | LIVE | None |
| Message | Events → text | `GET /evidence/events` | `EventDTO.message` | `get_recent_events()` | Derived from event fields | LIVE | event_type |
| Severity | Events → dot | `GET /evidence/events` | `EventDTO.severity` | `get_recent_events()` | Derived from event type keywords | LIVE | "INFO" |
| Details | Events → expand | `GET /evidence/events` | `EventDTO.details` | `get_recent_events()` | `decisions.jsonl → details/diag` | LIVE | {} |

---

## Source of Truth Summary

| Data Domain | Authoritative Source | Storage | Dashboard Read Method |
|---|---|---|---|
| Account (equity, balance, margin) | MT5 broker via RPyC | Live query | `mt5linux.MetaTrader5.account_info()` |
| Positions (open) | MT5 broker via RPyC | Live query | `mt5linux.MetaTrader5.positions_get()` |
| Risk observations | RiskObserver engine | `risk_state.json` (**loop-written**; dashboard live-compute is in memory only — 2026-09-25) or live computation | `get_risk_state()` (read-only) |
| Risk envelope | RiskEnvelope config | `config.toml` | `RiskEnvelope.from_config()` |
| Health state | Supervisor health file | `last_health.json` | `get_system_health()` |
| Build identity | Build pinning module | Live computation | `compute_build_identity()` |
| Events / Decisions | R4 loop decisions ledger | `decisions.jsonl` | `get_recent_events()` |
| Alerts | Alert engine + monitor | `alerts.jsonl` + `monitor.jsonl` | `get_recent_alerts()` |
| Qualification | Evidence pipeline | `qualification_status.json` (**pipeline-written**; dashboard fallback is in memory only — 2026-09-25) | `get_qualification_status()` |
| Shadow REDUCED | Shadow engine | `shadow_reduced.json` | `get_shadow_reduced()` |
| Reconciliation | Reconciliation engine | `reconciliation_state.json` (**engine-written**; dashboard fallback is in memory only — 2026-09-25) or derived | `get_reconciliation_status()` |

---

## Critical Integrity Rules

1. **Single source of truth** — Each dashboard value has ONE authoritative source. The dashboard never recalculates risk, never independently computes exposure, never derives authorization from its own logic.

2. **Missing ≠ zero** — When MT5 is unavailable, account fields return `0` with `freshness: UNKNOWN` and `source: "unavailable"`. The frontend must render these as "No data", never as `$0.00`.

3. **Stale ≠ live** — Data older than 30s is marked `STALE`. Data older than 5min is `UNKNOWN`. The frontend must visually distinguish these states.

4. **Never modify R4** — The dashboard has zero write paths. No POST/PUT/PATCH/DELETE endpoints. CORS allows only GET.

5. **Dashboard cannot control trading** — Authorization, risk limits, position management, and order execution are completely independent of dashboard availability.
6. **Single writer per state file** — each loop-owned state file has exactly one writer (the owning engine); the dashboard computes fallbacks in memory and never persists into loop-owned paths (contract §4; dashboard write-paths removed 2026-09-25).
7. **No unbacked lifecycle states / no proxy checks** — UI lifecycle steps require per-ticket event correlation (contract T1; hardcoded strip removed 2026-09-25); gates/badges reflect the dimension they name (contract T2).
8. **Authenticated live transport** — `WS /ws/live` requires the dashboard API key (token query param or Bearer header; unauthorized handshakes closed with code 1008), with one shared broadcaster loop and a cached state snapshot instead of per-connection MT5 polling (2026-09-25).
