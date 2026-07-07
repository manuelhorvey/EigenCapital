# state.json Schema Reference

**File**: `data/live/state.json`  
**Generated**: Every engine cycle (~60s) via `engine_state_service.py:save_state()`

---

## Top-Level Structure

```json
{
  "_checksum": "sha256_hex",
  "schema_version": "1.0.0",
  "contract_version": 2,
  "timestamp": "2026-07-07T10:30:00-04:00",
  "sequence_id": 1423,
  "portfolio": { ... },
  "assets": { "GC": { ... }, "USDCHF": { ... }, ... },
  "risk_parity": { ... },
  "halt_conditions": { ... },
  "open_positions": { "GC": { ... }, ... },
  "engine_status": { ... },
  "risk_signals": { ... } | null,
  "shadow_actions": { ... } | null,
  "emergency_halt": false,
  "halt_reason": "",
  "halt_detail": "",
  "peak_portfolio_value": 102345.67,
  "peak_capital_base": 100000.0,
  "breaker_daily_pnl": [12.3, -5.1, ...],
  "mt5": { ... }
}
```

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `_checksum` | string | `atomic_write_json()` | SHA256 of sorted JSON body (without `_checksum` itself). Used for integrity verification. |
| `schema_version` | string | `state/__init__.py:SCHEMA_VERSION` | `"1.0.0"` — state schema version |
| `contract_version` | int | `EngineSnapshot.CONTRACT_VERSION` | `2` — immutable contract version (checked at load) |
| `timestamp` | string | `engine_state_service.py` | ISO-8601 timestamp in US/Eastern |
| `sequence_id` | int | `state_store` | Monotonic cycle counter — increments each time state is persisted |
| `portfolio` | dict | `_compute_portfolio_summary()` | Portfolio-level metrics and state |
| `assets` | dict | `get_state()` | Per-asset state, keyed by asset name (22 entries) |
| `risk_parity` | dict | `get_state()` | Risk parity weight allocations and capital assignments |
| `halt_conditions` | dict | `engine._engine_cfg.halt` | Halting configuration (DD limit, consec loss threshold, etc.) |
| `open_positions` | dict | `save_state()` | Currently open position details, keyed by asset name |
| `engine_status` | dict | `save_state()` | Engine initialization and timing |
| `risk_signals` | dict\|null | `save_state()` | Per-asset risk signals (null if none active) |
| `shadow_actions` | dict\|null | `save_state()` | Shadow actions for comparison (null if none) |
| `emergency_halt` | bool | `orchestrator._emergency_halt` | True when circuit breaker has halted all trading |
| `halt_reason` | string | `orchestrator._halt_reason` | Enum value: `DRAWDOWN`, `CONSECUTIVE_LOSSES`, `VOL_SPIKE`, etc. |
| `halt_detail` | string | `orchestrator._halt_detail` | Human-readable halt explanation |
| `peak_portfolio_value` | float\|null | `orchestrator._peak_portfolio_value` | All-time peak portfolio MTM value |
| `peak_capital_base` | float\|null | `engine._engine_cfg.capital` | Capital base at last peak (stale detection) |
| `breaker_daily_pnl` | list[float]\|null | `CircuitBreaker.snapshot_state()` | Last 21 daily PnL values for breaker state |
| `mt5` | dict | `save_state()` | MT5 bridge connection status + account summary |

---

## `portfolio` Object

```json
{
  "total_value": 101234.56,
  "mtm_value": 101234.56,
  "total_return": 1.23,
  "realized_value": 100456.78,
  "realized_return": 0.46,
  "unrealized_pnl": 777.78,
  "days_running": 14,
  "runtime_hours": 342.5,
  "start_date": "2026-06-23",
  "start_datetime": "2026-06-23T09:30:00-04:00",
  "last_update": "2026-07-07T10:30:00-04:00",
  "capital": 100000.0,
  "allocations": { "GC": 7.0, "USDCHF": 4.0, ... },
  "deployment_cleared": true,
  "open_positions": 5,
  "closed_trades": 42,
  "execution_state": "ACTIVE",
  "weekend_cycle": false,
  "average_validity_exposure": 0.85,
  "portfolio_drawdown": -0.0234,
  "portfolio_peak_value": 103456.78,
  "position_concentration": { ... },
  "factor_exposures": { ... },
  "live_sharpe": { ... },
  "edge_health": { ... },
  "pek": { ... },
  "admission": { ... },
  "tripwire_states": { ... }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `total_value` | float | Current total portfolio MTM value |
| `mtm_value` | float | Same as `total_value` (duplicate for backward compat) |
| `total_return` | float | Total return % (MTM - capital) / capital × 100 |
| `realized_value` | float | Capital + sum of all realized PnL |
| `realized_return` | float | Realized return % |
| `unrealized_pnl` | float | Sum of MTM - current_value across all assets |
| `days_running` | int | Calendar days since engine start |
| `runtime_hours` | float | Total runtime in hours |
| `start_date` | string | Engine start date (YYYY-MM-DD) |
| `start_datetime` | string | Engine start datetime (ISO-8601, ET) |
| `last_update` | string\|null | Last refresh timestamp (ISO-8601, ET) |
| `capital` | float | Config baseline capital ($100K for paper) |
| `allocations` | dict | Per-asset allocation % as configured |
| `deployment_cleared` | bool | Always true (legacy deployment check) |
| `open_positions` | int | Count of assets with active positions |
| `closed_trades` | int | Total trade log entries across all assets |
| `execution_state` | string | `"ACTIVE"` / `"HALTED"` / `"PAUSED"` |
| `weekend_cycle` | bool | True during weekend filtered cycles |
| `average_validity_exposure` | float | Mean validity exposure [0–1] across all assets |
| `portfolio_drawdown` | float | Current drawdown fraction (negative, e.g. -0.0234 = -2.34%) |
| `portfolio_peak_value` | float\|null | All-time high MTM for drawdown computation |
| `position_concentration` | dict | Net-short skew, threshold, alert flag |
| `factor_exposures` | dict | Per-factor group exposures |
| `live_sharpe` | dict | Live Sharpe computed from equity history |
| `edge_health` | dict | Edge health monitor summary |
| `pek` | dict | PEK state (performance_state, risk_budget, portfolio_snapshot) |
| `admission` | dict | PEK admission controller result |

### `portfolio.pek.performance_state`

| Field | Type | Description |
|-------|------|-------------|
| `outcome_scalar` | float | Outcome-based risk scalar [0–1] |
| `degradation_scalar` | float | Degradation detection scalar [0–1] |
| `market_scalar` | float | Market condition scalar |
| `execution_scalar` | float | Execution quality scalar |
| `velocity_scalar` | float | Composite velocity scalar [0.5–1.5] |
| `composite_scalar` | float | Composite performance scalar |
| `win_rate_20` | float | Win rate over last 20 trades |
| `consecutive_losses` | int | Current consecutive loss streak |
| `r_cumulative_20` | float | Cumulative R over last 20 trades |
| `calibration_ece` | float | Calibration expected calibration error |
| `atr_ratio` | float | Current ATR / baseline ATR ratio |
| `regime_label` | string | Current regime label |
| `slippage_p90` | float | 90th percentile slippage |
| `velocity` | dict\|null | Velocity sub-object (see below) |

### `portfolio.pek.performance_state.velocity`

| Field | Type | Description |
|-------|------|-------------|
| `pnl_velocity` | float | Rate of change of PnL |
| `pnl_acceleration` | float | Acceleration of PnL |
| `vol_velocity` | float | Rate of change of volatility |
| `degradation_velocity` | float | Rate of change of degradation signal |
| `execution_velocity` | float | Rate of change of execution quality |

### `portfolio.pek.risk_budget`

| Field | Type | Description |
|-------|------|-------------|
| `max_risk_per_trade_pct` | float | Max risk per trade as % of equity |
| `max_portfolio_heat` | float | Max total portfolio heat |
| `max_concurrent_positions` | int | Max concurrent positions |
| `volatility_scalar` | float | Volatility-based budget scalar |
| `drawdown_scalar` | float | Drawdown-based budget scalar |
| `performance_scalar` | float | Performance-based budget scalar |
| `velocity_scalar` | float | Velocity-based budget scalar |

### `portfolio.pek.portfolio_snapshot`

| Field | Type | Description |
|-------|------|-------------|
| `total_equity` | float | Total equity (MTM) |
| `drawdown_pct` | float | Drawdown as fraction |
| `gross_exposure` | float | Gross notional exposure |
| `net_exposure` | float | Net notional exposure |
| `open_position_count` | int | Number of open positions |
| `daily_pnl` | float | Today's PnL |
| `max_daily_loss` | float | Maximum allowed daily loss |
| `daily_loss_remaining` | float | Remaining daily loss budget |
| `drawdown_remaining` | float | Remaining drawdown budget |
| `leverage_remaining` | float | Remaining leverage budget |
| `max_leverage` | float | Max allowed leverage |
| `concurrent_remaining` | int | Remaining concurrent position slots |
| `max_concurrent` | int | Max concurrent position slots |

### `portfolio.live_sharpe`

| Field | Type | Description |
|-------|------|-------------|
| `available` | bool | Whether sufficient data exists |
| `cycle_sharpe_adj` | float\|null | Cycle-level Lo-adjusted Sharpe |
| `daily_sharpe_7d` | float\|null | 7-day rolling daily Sharpe |
| `daily_sharpe_30d` | float\|null | 30-day rolling daily Sharpe |
| `daily_sharpe_all` | float\|null | All-time daily Sharpe |
| `portfolio_return_pct` | float | Cumulative return % |
| `max_drawdown_pct` | float | Max drawdown % |
| `n_days` | int | Number of trading days with data |
| `slippage_rms_pct` | float\|null | RMS slippage estimate from trace.jsonl |

---

## `assets` Object

Each key is an asset name (e.g. `"GC"`, `"USDCHF"`, `"BTCUSD"`). Value:

| Field | Type | Description |
|-------|------|-------------|
| `metrics` | dict | Per-asset metrics (see below) |
| `halt` | dict | Halt state (halted bool, reasons) |
| `validity_state` | string | `"GREEN"` / `"YELLOW"` / `"RED"` |
| `validity_exposure` | float | Exposure fraction [0–1] |
| `last_signal` | dict\|null | Most recent signal from prob_history |
| `gate_override` | bool | Whether governance gate is overriding |
| `signal_flip` | bool | Current signal opposes position direction |
| `final_signal` | string\|null | `"BUY"` / `"SELL"` / `"FLAT"` after governance |
| `execution_state` | string | `"ACTIVE"` / `"HALTED"` |
| `sl_mult` | float | Current SL multiplier |
| `tp_mult` | float | Current TP multiplier |
| `meta_confidence` | float\|null | Meta-label confidence [0–1] |
| `meta_decision` | string\|null | Meta-label decision |
| `feature_stability_jaccard` | float\|null | Jaccard similarity of top-10 features vs training |
| `feature_stability_spearman` | float\|null | Spearman rank correlation vs training |
| `sell_only` | bool | Whether asset is in SELL_ONLY_ASSETS |
| `tripwire_active` | bool | SELL tripwire warning active |
| `liquidity_regime` | string | `"NORMAL"` / `"THIN"` / `"STRESSED"` |
| `liquidity_sl_mult` | float | Liquidity-based SL multiplier |
| `liquidity_size_scalar` | float | Liquidity-based size scalar |
| `narrative_sl_mult` | float | Narrative-based SL multiplier |
| `narrative_size_scalar` | float | Narrative-based size scalar |
| `narrative_regime` | string\|null | Narrative regime label |
| `narrative_stale` | bool | Whether narrative data is stale |
| `regime_geometry` | dict | Per-asset regime geometry multipliers |
| `soft_warnings` | list[str] | Active soft warning messages |
| `stop_out_last_side` | string\|null | Last stop-out direction |
| `stop_out_last_cycle` | int\|null | Cycle ID of last stop-out |
| `total_exits` | int | Total trade exits |
| `sl_exits` | int | Exits due to SL hit |
| `sl_hit_rate` | float\|null | SL hit rate (sl_exits / total_exits) |
| `last_regime_long_prob` | float\|null | Last regime model long probability |
| `last_regime_label` | string\|null | Last regime classification label |
| `sizing_chain` | dict\|null | Sizing chain decomposition (eff_cap, scalar, dd, etc.) |
| `reentry_positions` | list[dict] | Pending re-entry positions |

### `assets[].metrics`

Same format as returned by `AssetEngine.get_metrics()`:

| Field | Type | Description |
|-------|------|-------------|
| `total_return` | float | Asset return % |
| `drawdown` | float | Asset drawdown % |
| `profit_factor` | float | Profit factor (gross profit / gross loss) |
| `n_trades` | int | Trade count |
| `mean_confidence` | float | Mean signal confidence % |
| `signal_distribution` | dict | `{ "BUY": N, "SELL": N, "FLAT": N }` |
| `win_rate` | float | Win rate [0–1] |
| `avg_r` | float | Average R-multiple |
| `cumulative_r` | float | Cumulative R-multiple |
| `max_dd_r` | float | Max drawdown in R-units |

### `assets[].halt`

| Field | Type | Description |
|-------|------|-------------|
| `halted` | bool | Whether asset is halted |
| `reasons` | list[str] | Halt reason strings |
| `soft_warnings` | list[str] | Warning messages (non-halting) |
| `drawdown_dd` | float\|null | Drawdown that triggered halt |
| `monthly_pf` | float\|null | Monthly profit factor |
| `signal_drought_days` | int\|null | Days without signal |
| `prob_drift` | float\|null | Confidence drift from baseline |

### `assets[].last_signal`

| Field | Type | Description |
|-------|------|-------------|
| `signal` | string | `"BUY"` / `"SELL"` / `"FLAT"` |
| `confidence` | float | Model confidence [0–100] |
| `close_price` | float | Price at signal time |
| `timestamp` | string | Signal timestamp (ISO-8601, ET) |
| `prob_long` | float | Raw long probability |
| `prob_short` | float | Raw short probability |

---

## `risk_parity` Object

```json
{
  "weights": { "GC": 0.07, "USDCHF": 0.04, ... },
  "capital_allocations": { "GC": 7000.0, "USDCHF": 4000.0, ... },
  "total_value": 101234.56
}
```

| Field | Type | Description |
|-------|------|-------------|
| `weights` | dict | Per-asset weight fractions |
| `capital_allocations` | dict | Per-asset capital in USD |
| `total_value` | float | Total portfolio MTM (duplicate of portfolio.total_value) |

---

## `open_positions` Object

Keyed by asset name. Each value:

| Field | Type | Description |
|-------|------|-------------|
| `position` | dict | Position core fields (side, entry, sl, tp, vol, layers) |
| `position.side` | string | `"long"` / `"short"` |
| `position.entry` | float | Entry price |
| `position.sl` | float | Stop loss price |
| `position.tp` | float | Take profit price |
| `position.entry_date` | string | Entry date (ISO-8601) |
| `position.vol` | float | Position volume |
| `position.mt5_ticket` | int\|null | MT5 ticket number |
| `position.layers` | list | Scale-out layer definitions |
| `position.avg_price` | float | Average entry price |
| `position.total_size` | float | Total position size |
| `position.base_entry_size` | float | Base entry size before scaling |
| `current_value` | float | Current position MTM value |
| `peak_value` | float | Peak position MTM value |
| `running_mae` | float\|null | Maximum adverse excursion |
| `running_mfe` | float\|null | Maximum favorable excursion |
| `bars_at_entry` | int | Number of bars since entry |
| `initial_sl` | float\|null | Original SL price |
| `initial_tp` | float\|null | Original TP price |
| `trade_log` | list[dict] | Position trade log entries |
| `prob_history` | list[dict] | Signal probability history |
| `adaptive_exit_phase` | string | `"STATIC"` / `"BE_LOCK"` / `"TRAILING"` / `"TIME_DECAY"` |
| `peak_mfe_r` | float\|null | Peak MFE in R-units |
| `sl_update_count` | int | Number of SL updates applied |

---

## `mt5` Object

| Field | Type | Description |
|-------|------|-------------|
| `connected` | bool | MT5 bridge connection status |
| `status` | string | `"CONNECTED"` / `"DISCONNECTED"` |
| `last_heartbeat` | string\|null | Last heartbeat timestamp (ISO-8601, ET) |
| `account` | dict\|null | Account summary (see below) |

### `mt5.account`

| Field | Type | Description |
|-------|------|-------------|
| `total_cash` | float | Account cash balance |
| `buying_power` | float | Available buying power |
| `portfolio_value` | float | Account equity (balance + unrealized PnL) |
| `positions` | list[dict] | Open MT5 positions |

### `mt5.account.positions[]`

| Field | Type | Description |
|-------|------|-------------|
| `asset` | string | Asset ticker |
| `quantity` | float | Position quantity |
| `avg_entry_price` | float | Average entry price |
| `current_price` | float | Current market price |
| `unrealized_pnl` | float | Unrealized PnL |
| `realized_pnl` | float | Realized PnL (0 for open positions) |
| `position_id` | int | MT5 position ID |

---

## Schema Version History

| Version | Date | Changes |
|---------|------|---------|
| `1.0.0` | 2026-07-02 | Initial documented schema |
| `1.0.1` | 2026-07-05 | Added `edge_health`, `admission`, `stop_out_last_*` fields |
| `1.0.2` | 2026-07-07 | Added `reentry_positions`, `sizing_chain`, `slippage_p90` to PEK |

---

**Last updated:** 2026-07-07
