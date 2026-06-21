# QuantForge — Paper Trading Runbook

Operational procedures for the paper trading system. This document is for the person responsible for monitoring and maintaining the live paper trading instance.

---

## Quick Reference

| Item | Value |
|------|-------|
| Start command | `./monitor_all` |
| Dashboard URL | `http://127.0.0.1:5000` |
| Config file | `configs/paper_trading.yaml` |
| State file (JSON) | `data/live/state.json` |
| State store (SQLite) | `data/live/state.db` (5 tables: trades, attribution, shadow_trades, confidence_buckets, equity_history) |
| Model files | `paper_trading/models/*.json` (base), `models/regime/*.json` (regime) |
| Logs | stdout (redirect to file as needed) |
| Refresh interval | 30s (configurable via `QUANTFORGE_REFRESH_INTERVAL` env var) |
| Weekend behavior | Auto-pauses Fri 17:00 ET — Sun 17:00 ET; no signal computation occurs |
| Weekend polling | Reduced to every 120s (state) / 5 min (secondary endpoints) |
| Market hours logic | `paper_trading/ops/market_hours.py` — `is_market_closed()` |
| Retrain frequency | Annual (January 1) |
| Training window | 5-year expanding |
| Feature build window | 500d (inference truncation validates and trims to 250d for XGBoost hot path) |
| Hardening history | `docs/archive/research_system_v1/HARDENING_ROADMAP.md` |
| Benchmarks | `benchmarks/README.md` (reference: 1.63s warm p50 for 15 assets, 8 workers) |

### Assets

**Core portfolio (18 assets promoted from walk-forward screening):**

Each asset uses risk-parity allocation with per-asset sl_mult, tp_mult, and max_depth calibrated via walk-forward optimization.

**Removed 2026-06-20:** AUDNZD, EURUSD, AUDCHF, GBPNZD (directional instability failure mode). USDCAD and NZDUSD halved from 5%→2.5%.

| Asset | Ticker | Allocation | sl_mult | tp_mult | max_depth |
|---|---|---|---|---|---|---|---|
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

**Total allocation: ~0.95** (remaining capacity held as cash buffer).

**Backtest performance (pre-leak-fix baseline, 5-year: 2021–2025):** PF 1.908, avgR +0.268, 2383 trades, 18 assets.
> Note: These are the screening baseline. Current walk-forward diagnostics after look-ahead fixes
> show lower, honest metrics. Live performance will differ.

**SL/TP Architecture:** Barriers are computed by `DynamicSLTPEngine` using `shared/volatility.py:VolatilityPrimitive` with `method="atr"`. At entry, initial barriers are set. On each refresh within the first `post_adjust_interval_bars` (default 3), `post_entry_adjust()` recomputes barriers based on current ATR — vol spikes (>1.3×) tighten SL; vol collapses (<0.7×) no action. Model-validity adjustments via per-asset `regime_geometry` in `configs/paper_trading.yaml` — each asset defines its own GREEN/YELLOW/RED multipliers for sl_mult and tp_mult.

**Meta-Confidence as Size Scalar:** The XGBoost-based `MetaLabelModel` produces a continuous probability. Below `threshold` (0.55 for most assets), trade notional is 0. Above threshold, `_meta_size_multiplier()` maps [threshold, 1.0] → [min_size, 1.0] linearly. Meta-confidence never modifies TP geometry, trailing, or scale-out schedules.

**Scale-Out Strategy:** Profit-taking is split into configurable tiers via `ScaleOutEngine` in `paper_trading/position/scale_out.py`. Tier profiles are generated dynamically by `entry/tp_compiler.py:_generate_scale_out_profile()` based on archetype and convexity — typically 4 equal tiers (25% at 0.25× / 0.50× / 0.75× / 1.00× of original TP multiplier). Stop-loss moves to breakeven after Tier 1 fills. See `ScaleOutEngine` in `paper_trading/position/scale_out.py`.

**Dashboard features:** Per-asset scale-out tier progress visualization (filled vs pending tiers shown as color-coded blocks in AssetCard). SL/TP hit rate gauge bars (GREEN/YELLOW/RED thresholds) in the Trade Outcomes table. PSI Drift panel with per-feature distribution shift scores, trend arrows, and color-coded classification badges. **Satellite card** shows entry price, stop price, target price when position active; SL/TP show `—` when flat; last exit reason (SL_HIT/TP_HIT/GATE_CLOSED) is displayed after each exit.

**Execution Dashboard (6 layers):** The Execution section (between Signals and Trades in the anchor nav) provides causal traceability across the full prediction → execution → exit → friction chain:
- **Layer 0 — FilterBar**: Persistent archetype/regime/asset filter chips that scope all execution views.
- **Layer 1 — ExecutionQualityStrip**: KPI row showing EIS (Execution Impact Score) and FQI (Fill Quality Index) per asset. EIS = slippage(40%) + fill quality(35%) + latency(25%). FQI = fill ratio × gap × partial × latency penalties.
- **Layer 2 — Attribution Breakdown**: Domain scores grid (Prediction/Execution/Exit/Friction) + PnL Waterfall bar chart decomposing gross PnL into prediction contribution, execution cost, friction cost, and net.
- **Layer 3 — MAE/MFE Scatter**: Scatter plot of max adverse/favorable excursion per trade, colored by archetype. Useful for detecting archetype-specific exit failure modes.
- **Layer 4 — Execution Friction**: Slippage histogram (entry/exit distribution with mean line) + Fill Quality gauge (SVG arc showing composite FQI with fill ratio, gap, partial, and latency annotations).
- **Layer 5 — Trade Execution Table**: Full attribution field table (archetype, R, entry/exit slippage, fill%, latency, MAE, MFE, exit reason) with row-click drill-down to `TradeDetailPanel` showing per-domain scores with progress bars.
- **Layer 6 — Shadow Comparison**: Divergence rate bar chart by config label + comparison table showing shadow vs live exit reasons, R delta, and MATCH/DIVERGE status.

**Dashboard UI:**
- **Anchor nav** — sticky horizontal nav bar below header (Portfolio/Signals/Execution/Trades/Governance/Risk/Charts). Click to jump, highlights current section on scroll via `IntersectionObserver`.
- **Sortable tables** — click any column header to sort ascending/descending. Sort state persists in `sessionStorage` per table (per-tab, cleared on tab close). Signals table defaults to confidence descending; Trades defaults to exit date descending.
- **Trend indicators** — portfolio metric cards show up/down arrows with Return and Realized P&L. Card trend color matches direction.
- **Governance row accents** — each governance row has a 3px left-border strip colored by premature-stop classification (GREEN/YELLOW/RED/INIT). RED rows have an animated pulse ring.
- **Data-fetching opacity** — the main content area dims to 0.7 opacity during background refetches (zero-JS CSS transition via `data-fetching` attribute).
- **Empty state differentiation** — "no results" from a search filter shows a `SearchSlash` icon; genuinely empty sections show an `Inbox` icon.
- **ConnectionStatus bar** — header bar monitors 5 endpoints (`/ping`, `/state.json`, `/narrative.json`, `/governance.json`, `/risk_parity.json`). Shows **Live** (green, all OK), **Degraded** (yellow, 1–2 failing), **Offline** (red, 3+ failing). Hover tooltip lists per-endpoint status.
- **AlertFeed** — captures governance halt/state-change and PSI-SEVERE events in real time. Persisted in `sessionStorage`. Dismissible per-event with severity badge.
- **RiskParityPanel** — bar chart of target allocations colored by governance state (RED/YELLOW/GREEN). Equal-weight reference line. Total allocation footer.
- **GovernanceStateCards** — per-asset governance summary with halted left-border accent, validity state badge, status tooltips.
- **Zod validation** — every API response is validated against a Zod schema at fetch time. Mismatches are logged to console and surface as a panel-level error fallback instead of silent NaN/undefined propagation.

### Governance Overlays

The system applies three independent governance layers on top of the base SL/TP chain:

- **Macro Narrative (weekly)**: FXStreet article → Claude LLM → geopol risk score + regime. SL widens +10% when geopolitics > 0.7. Size reduces -20% when risk_off. Human confirm step via dashboard.
- **Liquidity Regime (per-tick)**: Volume z-score + Amihud ratio from daily OHLCV. THIN → SL +15%, size -15%. STRESSED → SL +30%, size -30%, halted.
- **PSI Drift (per-cycle)**: Top-10 feature distribution shift detection vs training baseline. MODERATE → -0.08 validity penalty. SEVERE → -0.20 validity penalty. 3+ SEVERE → hard halt.

SL chain: `final_sl = base × regime_geom × narrative_sl × liquidity_sl`  
Validity stack: `score = base − penalties + stability_penalty + psi_penalty`

### Governance Config Reference

| Key | Default | Description |
|-----|---------|-------------|
| `narrative_config.enabled` | true | Enable weekly macro narrative |
| `narrative_config.geopol_sl_widen_pct` | 10 | SL widen % on geopol risk |
| `narrative_config.risk_off_size_reduce_pct` | 20 | Size reduce % on risk_off |
| `narrative_config.min_confidence` | 0.6 | Min LLM confidence |
| `narrative_config.auto_confirm_deadline_hour` | 12 | Auto-confirm deadline (ET) |
| `liquidity_config.volume_z_thin_threshold` | -1.5 | Volume z → THIN |
| `liquidity_config.volume_z_stressed_threshold` | -2.5 | Volume z → STRESSED |
| `liquidity_config.amihud_high_threshold` | 1.5 | Amihud z → THIN |
| `liquidity_config.amihud_stressed_threshold` | 3.0 | Amihud z → STRESSED |
| `liquidity_config.thin_sl_widen_pct` | 15 | SL widen in THIN |
| `liquidity_config.thin_size_reduce_pct` | 15 | Size reduce in THIN |
| `liquidity_config.stressed_sl_widen_pct` | 30 | SL widen in STRESSED |
| `liquidity_config.stressed_size_reduce_pct` | 30 | Size reduce in STRESSED |

### Halt Parameters (global defaults, overridable per asset)

Per-asset:
```
drawdown: -0.08       # Per-asset drawdown limit
monthly_pf: 0.70      # Minimum monthly profit factor
signal_drought: 30    # Max days without a signal
prob_drift: 0.25       # Max confidence drift from expected baseline (skipped if < 10 signals)
```

Portfolio-level:
```
portfolio_drawdown_limit: -0.15   # Force-close ALL positions when total equity drawdown ≤ -15%
```

Per-asset trade quality config (all assets):
```
config:
  min_confidence: 50      # Skip entry if model confidence < 50%
  max_holding_days: 30    # Force-close after N calendar days (reason: time_stop)
```

### Position Sizing Guardrail Config (Global Defaults)

| Key | Default | Description |
|-----|---------|-------------|
| `max_position_pct_of_equity` | 15% | Per-position notional cap as % of total equity |
| `max_risk_per_trade_pct` | 2.0% | Max SL risk per trade as % of equity |
| `min_viable_position_pct` | 1.0% | Min viable position notional; skip if risk cap shrinks below this |
| `size_taper_start_dd` | -5% | Drawdown starts tapering size at this level |
| `size_taper_end_dd` | -15% | Drawdown hits min_size at this level |
| `size_taper_min` | 50% | Minimum size multiplier when drawdown exceeds end_dd |
| `portfolio_max_leverage` | 2.0x | Max portfolio notional leverage against equity |
| `portfolio_leverage_tolerance` | 0.1% | Tolerance factor for backstop floating-point comparison |

---

## 1. Daily Procedure

### Morning Check (before market open, ~08:30 ET, Mon–Fri)

```
./monitor_all
```

The script:
1. Loads cached models from `paper_trading/models/`
2. Downloads fresh OHLCV data via MT5 / yfinance
3. Downloads macro data (DXY, VIX, SPX, WTI, TNX) via yfinance
4. Computes alpha + regime + archetype features
5. Runs inference on all assets (base model — ensemble disabled portfolio-wide)
6. Applies decision pipeline stages (19 stages: first-cycle suppression → bar-jump → resolve signal → risk-off → sell-only filter → spread gate → stability → hysteresis → conviction → profit lock → manage position → route execution → poll deferred)
7. Routes through 11 governance layers + HealthMonitor (circuit breaker, VaR/CVaR, equity cluster alarm) + RecoveryScheduler
8. Opens/closes positions based on signal vs current position (MT5 bridge + paper)
9. Serves dashboard on port 5000
10. Repeats every refresh interval (default 30s, configurable via `QUANTFORGE_REFRESH_INTERVAL` env var)

**Signal logging:** The `scripts/monitor_paper_trading.py` script polls the dashboard every 6 hours
and appends a CSV row to `data/monitoring/paper_trade_monitor.csv`. Use it for daily signal checks:

```bash
python scripts/monitor_paper_trading.py
```

**Weekend / after-hours:** The engine auto-detects market closure (Fri after 17:00 ET, all day Sat/Sun). Refresh cycles are skipped — no yfinance data pulls, no signal generation, no SL/TP checks. The dashboard stays live showing the last pre-close state with a yellow **CLSD** badge. Normal operation resumes at the next scheduled refresh after Sun 17:00 ET.

A quick health check via `/ping`:
```bash
curl http://127.0.0.1:5000/ping
# → {"status": "ok"}
```

**What to verify on the dashboard (use the anchor nav bar to jump between sections):**

- Portfolio total value and daily return are updating (trend arrows on metric cards show direction)
- All 18 assets show a signal (BUY/SELL/FLAT) with confidence — click column headers in the Signals table to sort by confidence descending
- Current price is within ~0.5% of market price
- No asset is in halt (check asset cards for RED status)
- Per-asset drawdown % is not approaching per-asset limits
- Portfolio drawdown value is not approaching -15% circuit breaker threshold
- After restart: cycle 1 shows `first-cycle suppression` in logs (normal), trades resume cycle 2+
- After MT5 reconnect: check for `bar-jump suppression` log — suppresses ~60min if bar count changed >100 (normal after source switch)
- Risk-off conditions: if VIX>0 & SPX<0, expect AUDUSD showing `risk-off suppression — holding flat` (validated behavior)
- Sell-only filter: 11 flagged assets (CADCHF, AUDUSD, ES, NQ, NZDCHF, EURAUD, ^DJI, USDCHF, EURCHF, NZDUSD, EURNZD) will show `sell-only filter — suppressing BUY signal` for BUY signals, holding flat instead
- Equity cluster alarm: if ES/NQ/^DJI all have open positions on the same side, expect `equity_cluster_all_LONG_ES_NQ_^DJI` or `equity_cluster_all_SHORT_ES_NQ_^DJI` recommendation logged by HealthMonitor
- Spread gate observe mode: in first 720 cycles (~6h), check for `spread gate would block` logs; after observation window, `spread gate blocked entry` is expected for high-spread conditions
- Market status badge shows **OPEN** (green) during trading hours, **CLSD** (yellow) on weekends
- **LAST** timestamp in the header shows when signals were last refreshed
- **Scale-out tiers** on open positions: check filled vs pending tier blocks in AssetCard
- **SL/TP gauge bars** in Trade Outcomes: GREEN TP rate (≥25%), GREEN SL rate (≤50%), GREEN flip rate (≤15%)
- **Narrative badge**: check overall_regime indicator (red/yellow/green/grey) and stale flag; check for **NARR PENDING** button or **NARR ERR** badge
- **Liquidity badge**: check for **LIQ THIN** (yellow) or **LIQ STRSD** (red); hover for per-asset breakdown
- **Governance rows**: left-border accent strips show per-asset premature-stop classification at a glance (green=good, yellow=caution, red=critical)
- **PSI Drift panel**: check for any MODERATE (amber) or SEVERE (red) feature classifications; note trend arrows — SEVERE + INCREASING arrow (red ↑) is a genuine drift signal, SEVERE + STABLE may be a data hiccup; look for **PSI HALT** badge on halted assets
- **ConnectionStatus bar**: verify header bar shows **Live** (green). If **Degraded** (yellow), hover to identify which endpoints are failing. If **Offline** (red), the dashboard has lost contact with the backend.
- **AlertFeed**: check the alert tray (below nav) for governance halts, state changes, or PSI-SEVERE events that may require attention. Dismiss acknowledged alerts.
- **RiskParityPanel**: verify target allocations sum to ~100%. Bars colored by governance state. Cross-reference halted assets against the Governance panel.
- **GovernanceStateCards**: check per-asset halted status (red left-border), validity state badge, and status tooltips.

### Log Check

After startup (Mon–Fri during market hours), verify log output shows signal lines for all 18 assets:
```
GC: BUY conf=XX% @ $XX.XX
USDCHF: BUY conf=XX% @ $XX.XX
...
Portfolio: $XXXXX (XX%)
```

If any asset shows `ERROR`, investigate immediately (see Halt Conditions).

### End of Day (~17:00 ET)

Run once more to capture the closing signal:
```
# If process is still running, signals refresh automatically
# If not, start it: ./monitor_all
```

After 17:00 ET on Friday, the engine auto-pauses for the weekend. The dashboard remains accessible, showing the pre-close state with a yellow CLSD badge. No further yfinance data or signal computation occurs until Sunday 17:00 ET.

Log the daily summary to a file:
```
python -c "
import json
with open('data/live/state.json') as f:
    s = json.load(f)
p = s['portfolio']
print(f'{p[\"total_value\"]:.2f} | {p[\"total_return\"]:.2f}% | Day {p[\"days_running\"]}')
for name, a in s['assets'].items():
    m = a['metrics']
    print(f'  {name}: {m[\"total_return\"]:.2f}% DD={m[\"drawdown\"]:.1f}% PF={m[\"profit_factor\"]:.2f} n={m[\"n_trades\"]}')
" >> data/live/daily_log.csv
```

---

## 2. Weekly Procedure

### Signal Distribution Check

Run the signal distribution summary:
```python
import json, pandas as pd
with open('data/live/state.json') as f:
    s = json.load(f)
for name, a in s['assets'].items():
    m = a['metrics']
    dist = m['signal_distribution']
    total = sum(dist.values())
    print(f"{name}: BUY={dist.get('BUY',0)} SELL={dist.get('SELL',0)} FLAT={dist.get('FLAT',0)} conf={m['mean_confidence']}%")
```

**Expectations:**

All 18 assets should show a balanced BUY/SELL ratio (~1:1) with mean confidence in the 55-75% range. For the 11 SELL_ONLY assets, expect FLAT to dominate BUY (BUY signals are overridden to FLAT). Deviations warrant investigation of the specific asset's governance state and recent market conditions.

### Narrative Check (Monday Morning)

On Monday before noon ET, verify the macro narrative pipeline ran:

```bash
curl http://127.0.0.1:5000/narrative.json | python3 -m json.tool
```

Check for:
- `"has_pending": true` — pipeline fetched but awaits confirmation. Click **NARR PENDING** on the dashboard or wait for auto-confirm at noon.
- `"needs_confirmation": true` — same as above; visible indicator present.
- `"active"` — narrative has been confirmed and is live. Check `overall_regime` and `confidence`.
- `"stale": true` — narrative is ≥7 days old. Governance not applied. Will refresh next Monday.
- `"fetch_error"` — scrape or LLM call failed. Check logs for details.

If the key `OPENCODE_ZEN_API_KEY` is not set, the pipeline will skip the LLM call and save a neutral narrative instead.

### Liquidity Check

Check for abnormal liquidity conditions via dashboard badges or API:

```bash
curl http://127.0.0.1:5000/liquidity.json | python3 -m json.tool
```

If any asset shows `"regime": "STRESSED"`, investigate whether this correlates with a macro event, data issue, or asset-specific factor.

**If ratio exceeds 3:1 in either direction**, investigate macro context. A sustained imbalance may indicate:
- A structural regime shift (e.g., persistent tightening)
- Feature drift (PSI > 0.25 on a key feature)
- Data feed issue (stale macro data)

### Drift Check (PSI Monitoring)

PSI drift is now **fully automated** — `monitoring/psi_monitor.py` computes per-feature PSI every cycle against the training baseline:

```bash
# Check automated drift status
curl http://127.0.0.1:5000/psi.json | python3 -m json.tool

# Check per-asset summary in dashboard
# Open http://localhost:5000 and find the PSI Drift panel
```

**What the automated system checks:**
- Top-10 features per asset (from importance tracker)
- Fixed-width 10-bin PSI against training distribution baseline
- Trend direction (STABLE / INCREASING / DECREASING) per feature vs previous cycle
- Penalty applied to validity score: MODERATE → −0.08, SEVERE → −0.20
- Hard halt when 3+ features simultaneously SEVERE

**PSI thresholds** (same as manual, now automated):
| Classification | PSI | Dashboard Color |
|---|---|---|
| NO_DRIFT | < 0.10 | Green |
| MODERATE | 0.10 – 0.20 | Amber |
| SEVERE | > 0.20 | Red |

**Trend interpretation:**
- **INCREASING** (↑) — genuine drift signal; PSI is rising cycle over cycle
- **STABLE** (→) — PSI unchanged from previous cycle; a SEVERE + STABLE reading may be a data glitch
- **DECREASING** (↓) — PSI is falling; distribution returning toward baseline

### Model Retrain Check

The first week of each year, verify the annual retrain ran:
```
ls -la paper_trading/models/*.json
```

Check the model file modification dates are within the expected retrain window.

If retrain failed:
```bash
cd /home/manuelhorveydaniel/Projects/QuantForge
source .venv/bin/activate
python -c "
from paper_trading.engine import PaperTradingEngine
engine = PaperTradingEngine()
for name in engine.assets:
    engine.assets[name].train(force=True)
    print(f'{name}: retrained')
"
```

---

## 3. Halt Condition Responses

The system has six independent halt mechanisms:

### 3.1 Validity State Machine (Automatic)

The `ValidityStateMachine` monitors model validity and adjusts capital allocation:

| State | Capital Allocation | Entry Condition | Exit Condition |
|-------|-------------------|-----------------|----------------|
| GREEN | 100% | Smoothed validity >= 0.70 | Smoothed validity < 0.60 |
| YELLOW | 50% | Smoothed validity >= 0.45 | Smoothed validity < 0.40 |
| RED | 0% | Smoothed validity < 0.40 | Smoothed validity >= 0.50 |

With inertia (α=0.7, β=0.3) and regime persistence lock (minimum 5 periods before state change).

**Response by state:**

- **YELLOW**: No action required. Note the transition in the weekly log. Check validity score components (confidence, feature drift, market conditions).
- **RED**: Stop and investigate. The engine will hold current positions at 0% allocation (no new entries, existing positions run to SL/TP). Do not restart until root cause is identified.

**To check current state:**
```python
import json
with open('data/live/state.json') as f:
    s = json.load(f)
for name, a in s['assets'].items():
    print(f"{name}: {a.get('validity_state', 'N/A')}")
```

### 3.2 Per-Asset Halt Conditions (Hard Limits)

Defined in `configs/paper_trading.yaml` per asset. The `check_halt_conditions()` method checks:

| Condition | Trigger | Response |
|-----------|---------|----------|
| Drawdown | Per-asset limit breached | Stop engine for that asset |
| Monthly PF | Below 0.70 for trailing month | Investigate model degradation |
| Signal drought | No signal for 30 days | Reduces validity score by -0.15. Checks `last_signal_date` vs `datetime.now()`. |
| Prob drift | Confidence drift > 0.25 | Reduces validity score by -0.15. Requires ≥10 signals for stable mean estimate. |

**When an asset halts:**
1. The engine continues running for non-halted assets
2. Log the halt with full context: `data/live/state.json` under the asset's `halt` field
3. The halted asset must be manually cleared to resume

**Response steps for a halted asset:**

```
1. Check the halt reason from state.json
2. Review recent signal history for the halted asset
3. Check macro data freshness (rate_diff, yields)
4. Check yfinance data availability for the ticker
5. Restart only after root cause is identified
```

To restart a halted asset, restart the engine:
```bash
# Stop current process (Ctrl+C), then:
./monitor_all
```

### 3.3 Portfolio-Level Circuit Breaker

The engine tracks portfolio peak value across ticks. On each `run_once()` cycle, before signal generation, the portfolio drawdown is computed:

```
portfolio_dd = (current_mtm - peak_value) / peak_value
if portfolio_dd ≤ portfolio_drawdown_limit:
    force-close ALL positions with reason "portfolio_circuit_breaker"
    skip signal generation for this cycle
```

**Parameters:**
| Setting | Default | Location |
|---------|---------|----------|
| `portfolio_drawdown_limit` | -0.15 (-15%) | `configs/paper_trading.yaml` top-level |

**When triggered:**
1. All open positions are immediately closed at current price
2. Signal generation is skipped for that cycle
3. The reason `portfolio_circuit_breaker` appears in the trade journal
4. The engine continues running — positions may re-enter on subsequent ticks if drawdown recovers

**This is the final safety layer** — it fires only when per-asset halts and validity state machines have already failed to contain losses.

### 3.4 Macro Narrative Governance (Weekly)

A weekly LLM-driven macro context overlay that adjusts SL width and position sizing based on FXStreet analysis:

| Condition | Trigger | Effect |
|-----------|---------|--------|
| Geopolitical risk | `geopol_risk_score > 0.7` | SL widens by `geopol_sl_widen_pct` (+10%) |
| Risk-off regime | `overall_regime == "risk_off"` | Position size reduced by `risk_off_size_reduce_pct` (-20%) |
| Low confidence | LLM `confidence < min_confidence` (0.6) | No governance applied |
| Stale narrative | ≥7 days since week_start | Governance suppressed; `(STALE)` badge on dashboard |

**Pipeline** — runs Monday before noon ET:
1. Fetches FXStreet "Week ahead" article via web scrape
2. Sends text to Claude API for structured JSON extraction
3. Output saved as `narrative_pending.json` on dashboard
4. Human confirms via **NARR PENDING** button; or auto-confirms after `auto_confirm_deadline_hour` (12:00 ET)
5. Active narrative applied to all assets: SL × `_narrative_sl_mult`, size × `_narrative_size_scalar`

**Failure modes:**
- Scrape failure → carries forward last week's narrative with `fetch_error` flag; yellow **NARR ERR** dashboard badge
- LLM parsing failure → neutral defaults applied
- No pending confirmation by deadline → auto-confirm at noon

**To check narrative status:**
```bash
curl http://127.0.0.1:5000/narrative.json
```

**Dashboards indicators:**
- **NARR PENDING** button — one-click confirm, shown when `needs_confirmation: true`
- **NARR ERR** badge — yellow/red when scrape or LLM fails
- **Regime badge** — color-coded text (risk_off=red, geopol_tension=yellow, risk_on=green, data_driven=grey)
- **(STALE)** suffix — appended when narrative exceeds 7-day window

### 3.5 Liquidity Regime Model (Per-Tick)

Real-time liquidity regime computed from daily OHLCV volume and price data on every signal cycle:

| Condition | Trigger | Effect |
|-----------|---------|--------|
| THIN regime | `volume_z < -1.5` OR `amihud_z > 1.5` | SL +15%, size -15% |
| STRESSED regime | `volume_z < -2.5` OR `amihud_z > 3.0` | SL +30%, size -30%, halted |
| NORMAL | All thresholds clear | No adjustment |

**Effect chain:** `final_sl = base_sl × regime_geom × narrative_sl × liquidity_sl`

**Dashboard indicators:**
- **LIQ THIN** (yellow badge) — one or more assets in THIN regime
- **LIQ STRSD** (red badge) — one or more assets in STRESSED regime (halted)
- Hover tooltip shows per-asset breakdown: `GC: THIN sl=1.15x size=0.85x`

**Response:**
- THIN regime: No action required. Monitor for progression to STRESSED.
- STRESSED regime: Check the affected asset(s) — the engine halts execution for those assets and logs the liquidity event. Review whether this correlates with a macro event or is asset-specific.

### 3.6 PSI Drift (Per-Cycle)

Automated distribution shift detection per feature per asset against the training baseline:

| Classification | PSI Range | Effect |
|----------------|-----------|--------|
| NO_DRIFT | < 0.1 | No action |
| MODERATE | 0.1 – 0.2 | −0.08 validity penalty |
| SEVERE | > 0.2 | −0.20 validity penalty |
| 3+ SEVERE | any | Hard halt (`psi_ok = False`) |

**Scoping:** Only top-10 features per asset (from importance tracker), computed on a rolling 21-day window.

**Trend tracking:** Each feature's PSI trend (STABLE / INCREASING / DECREASING) is tracked against the previous cycle. A SEVERE + INCREASING combination is a genuine drift signal; SEVERE + STABLE may be a data glitch.

**Dashboard indicators:**
- **PSI Drift panel** — per-asset table with feature rows, color-coded classification badges (green/amber/red), trend arrows (↑↓→)
- **PSI HALT** badge — shown on halted assets when `psi_ok = False` (3+ SEVERE features)

**To check PSI drift status:**
```bash
curl http://127.0.0.1:5000/psi.json | python3 -m json.tool
```

**Response:**
- MODERATE drift: No action required. Note the affected features.
- SEVERE drift on 1-2 features: Monitor. Check if trend is INCREASING (genuine drift) or STABLE (possible data glitch).
- SEVERE drift on 3+ features: Asset is halted by the engine. Investigate root cause — feature distribution shift may indicate a structural regime change or data pipeline issue.

### 3.7 Guardrail Events (Diagnostic)

The position sizing guardrails log their decisions. Monitor these in engine output:

**`SIZING <asset>: eff_cap=... base=... exp=... gov=... meta=... dd=... pos_cap=... risk_cap=... lev_budget=... -> final_not=... qty=...`**

Decomposed factors (paper sizing attribution):
- `eff_cap` — effective capital (base × min(growth, 3×))
- `base` — position_size scalar
- `exp` — exposure_multiplier
- `gov` — governance-derived portion (effective_cap × size_scalar / (position_size × exposure))
- `meta` — meta-confidence multiplier
- `dd` — drawdown taper multiplier
- `pos_cap` — max_position_pct_of_equity cap (absolute USD)
- `risk_cap` — max_risk_per_trade_pct cap (absolute USD)
- `lev_budget` — remaining leverage budget (absolute USD)
- `final_not` — final notional after all caps
- `qty` — final quantity

**`MT5_SIZING <asset>: equity=... dd=... max_pct=... risk_cap=... min_viable=... -> final_not=... qty=...`**

Same decomposed factors, sized against real broker equity.

**Guardrail skip reasons:**
- `risk cap would shrink position below min viable` — risk cap clipped below min_viable_position_pct
- `leverage budget exhausted` — portfolio leverage pool drained
- `below min volume` — MT5 qty converts to 0 lots (below broker min_volume)

### 3.8 Data Feed Failure

If yfinance returns empty or stale data for any ticker:

**Symptoms:**
- `ERROR - No live data for BTC-USD` in logs
- Dashboard shows stale prices (>24h old)
- Missing signals for that asset

**Response:**
1. Verify yfinance availability: `python -c "import yfinance as yf; d=yf.download('BTC-USD',period='5d'); print(d.empty)"`
2. Check internet connectivity
3. If yfinance is down, the engine will continue running but cannot generate new signals
4. If the outage exceeds one trading day, consider whether to halt

---

## 4. Six-Month Evaluation Criteria

After six months of paper trading, evaluate against these gates:

### Gate 1: Portfolio-Level Profitability
- Net return > 0% (absolute, not annualized)
- At least 4 of 6 monthly periods positive

### Gate 2: Per-Asset Bootstrap Pass Rate
Each asset must meet the deployment gate (from ADR-013):
- Bootstrap p < 0.10 on the full paper trading period
- Minimum 4 of 6 monthly windows pass the bootstrap test

### Gate 3: Signal Distribution Health
- No asset has BUY/SELL ratio > 3:1 over the evaluation period
- Mean confidence > 0.55 for each asset
- FLAT signal ratio < 50% (model is not becoming indecisive)

### Gate 4: Drawdown Management
- Maximum portfolio drawdown < 15%
- Time to recovery from max drawdown < 60 trading days
- No automatic halts triggered by validity state machine for the last 3 months

### Gate 5: Strategy Drift
- PSI < 0.25 for all features in all assets
- Feature importance rankings (if recomputed) are stable vs original SHAP analysis
- Profit factor rolling 3-month does not show monotonic decline

---

## 5. Real Capital Decision Framework

### What Pass Looks Like

All six-month evaluation gates pass. Additionally:

| Condition | Threshold | Evidence Required |
|-----------|-----------|-------------------|
| Sharpe ratio | > 0.50 | Bootstrap p < 0.05 |
| Max drawdown | < 12% | Daily PnL series |
| Win rate | > 45% | Trade log |
| Trade count | > 100/year | Per asset |
| Correlation drift | Max pairwise < 0.20 | Rolling 60-day correlation |

### Deployment Sequence

```
Phase 1: 25% capital ($25k on $100k plan)
  Duration: 3 months
  Monitoring: Daily (same as paper trading)
  Exit if: > 10% drawdown from peak

Phase 2: 50% capital ($50k)
  Duration: 3 months
  Monitoring: Daily
  Exit if: > 12% drawdown from peak

Phase 3: 100% capital ($100k)
  Duration: Ongoing
  Monitoring: Daily (reduced to weekly after 6 months stable)
```

### Risk Controls for Real Capital

Additional controls beyond paper trading:
- Hard stop-loss at portfolio level: -15% from peak
- Trade-level stop-loss: 2x volatility barrier (already in model)
- Maximum single-day loss: 3% of portfolio (triggers intraday halt)
- Weekly reconciliation: compare local state.json against broker positions

### What Fallback Looks Like

If six-month evaluation fails:
1. Return to research phase: re-run walk-forward on the paper trading period
2. Identify which asset(s) failed and which gate was breached
3. Open a new ADR for the required change
4. Re-validate with bootstrap before re-entering paper trading
5. Paper trading clock resets to month 1

---

## 6. Research Backlog

Items to build after paper trading confirms the system works.

### P0 — Ready for Development

| Item | Description | Depends On |
|------|-------------|------------|
| COT data pipeline | CFTC weekly parsing, daily interpolation, EURUSD features | Paper trading stable |
| Execution layer | Interactive Brokers/Alpaca order management | COT done |
| Risk parity allocation | Rolling covariance estimation, dynamic weights | 6 months of paper trading data |
| Automated retrain cron | Scheduled annual retrain without manual intervention | — |
| Automated PSI monitoring | Feature drift detection with alerting | — |

### P1 — Requires Design

| Item | Description | Depends On |
|------|-------------|------------|
| AUDJPY — RESOLVED (historical) | Added to prior portfolio iteration (5/5 WF windows, Sharpe 2.62). Correlated with NZDJPY (r=0.87) but diversifies JPY carry exposure. | — |
| Weekly timeframe models | Lower frequency for macro-only signals | Feature engineering |
| Meta-labeling refinement | Improved threshold calibration for meta-confidence sizing | More training data |
| Sector rotation extension | Apply driver atlas to ES/NQ equity index sectors | Paper trading results |
| Regime classifier V2 | Reduce volatility gate false positives | More regime diversity in data |

### P2 — Future Research

| Item | Description |
|------|-------------|
| Intraday models | 1-hour bars for FX (requires COT + tick data) |
| Options overlay | Covered call/cash-secured put on ES/NQ equity-index positions |
| Crypto expansion | ETH, SOL with momentum_crypto driver cluster |
| Cross-asset feature transfer | Transfer learning between driver clusters |
| LLM-based sentiment | Macro news sentiment as feature for FX |

---

## 6. Execution Physics and Sizing (Hardening)

Live paper trading applies **spread + impact** on entries and exits via `ExecutionBridge` (`paper_trading/execution/bridge.py`). Slippage and impact parameters are configured per-asset within `configs/paper_trading.yaml`.

**Position sizing guardrails** (applied multiplicatively in `entry_service.py:_submit_to_broker()`):

```
effective_cap × position_size × exposure × governance × meta × drawdown_taper
  → cap by max_position_pct_of_equity
  → cap by max_risk_per_trade_pct (skip if below min_viable_position_pct)
  → atomically decrement from portfolio leverage budget
```

Paper logs decomposed factors via `SIZING` line; MT5 logs via `MT5_SIZING` line (independent sizing from real broker equity).

**MT5 independent sizing**: `_compute_mt5_qty()` in `entry_service.py` fetches the real broker equity, applies drawdown taper + risk cap, validates against broker min_volume, and submits with the MT5-computed lot size (independently of paper's position size).

**Volatility dashboard** (`/volatility.json`) compares live vol to rolling baselines.

**Execution quality dashboard** (`/execution/quality.json`) — per-asset EIS and FQI scores. Use to detect execution degradation before it hits PnL (EIS < 0.5 or FQI < 0.6 warrants investigation).

**Attribution dashboard** (`/attribution/trades.json`, `/attribution/summary.json`, `/attribution/waterfall.json`) — 4-domain causal decomposition per trade:
- Check `domain_scores` in the summary: prediction_score < 0.3 suggests signal quality issue; execution_score < 0.4 suggests entry timing degradation; friction_score < 0.5 suggests spread/impact/latency problems.
- PnL waterfall shows where PnL was lost/gained across the 4 domains.
- Filter by `archetype` or `asset` to isolate specific conditions.

**Shadow divergence dashboard** (`/shadow/trades.json`, `/shadow/summary.json`) — live vs shadow counterfactual comparison:
- `divergence_rate` > 0.3 suggests the shadow SL/TP parameters are consistently diverging from live execution outcomes.
- High R delta (|ΔR| > 1.0) on diverged trades indicates a systematic exit logic gap.
- Check `by_label` breakdown to see which alt-config is diverging most.

**Analytics snapshot** (`/analytics/snapshot.json`) — aggregated summary of all metrics. Frequency-gated (recomputes every 5 requests). Useful for a single-call status overview.

**Decision payload** may include `macro_weight` when adaptive macro is active.

**Research / validation:** see `docs/archive/research_system_v1/HARDENING_ROADMAP.md` for extended history, lead-lag, and pytest targets.

---

## Appendix: File Locations

```
Project Root/
├── configs/
│   └── paper_trading.yaml        # Assets, halt, vol_baselines, execution_config
├── data/
│   ├── live/
│   │   ├── state.json            # Current portfolio and asset state (EngineSnapshot)
│   │   ├── state.db              # SQLite state store (WAL mode, O(1) append)
│   │   │   ├── trades            # Trade journal with exit reasons
│   │   │   ├── attribution       # 4-domain attribution records
│   │   │   ├── shadow_trades     # Counterfactual shadow trade records
│   │   │   ├── confidence_buckets # Per-asset confidence histogram buckets
│   │   │   └── equity_history    # Portfolio equity over time
│   │   ├── trade_outcomes.json   # Aggregated TP/SL/win rates (cached from SQLite)
│   │   ├── analytics_snapshot.json # Precomputed analytics (5-cycle gated)
│   │   ├── equity_history.json   # Legacy equity curve
│   │   ├── review_log.json       # Weekly review acknowledgment log
│   │   └── cache/                # Per-ticker OHLCV parquet cache
│   ├── research/
│   │   ├── lead_lag_matrix.parquet
│   │   ├── lead_lag_edges.yaml
│   │   ├── survival_*.json       # Baseline vs extended survival exports
│   │   └── attribution/          # Per-asset attribution parquet files
│   ├── raw/historical_extended/  # 2000+ OHLCV (after backfill)
│   └── processed/
│       ├── macro_factors.parquet # Macro data (yfinance-derived)
│       └── walkforward_summary.csv  # 30-asset walk-forward ranking
├── benchmarks/                   # Hot-path microbenchmark
│   ├── microbenchmark.py         # CLI: cold/warm cycles, sweep, profile
│   ├── mock_data.py              # MockDataFixture (synthetic OHLCV at yfinance boundary)
│   └── README.md                 # Reference numbers and usage
├── paper_trading/
│   ├── engine.py                 # PaperTradingEngine + PaperBroker
│   ├── asset_engine.py           # Per-asset lifecycle + _can_enter() entry gate
│   ├── state_store.py            # SQLite state store (5 tables, WAL mode)
│   ├── inference/
│   │   ├── pipeline.py           # Live inference pipeline (truncation, async diag)
│   │   ├── async_diagnostics.py  # DiagnosticsSnapshot + DaignosticsQueue daemon
│   │   └── training.py           # Binary XGBoost training pipeline
│   ├── orchestrator/
│   │   ├── engine.py             # EngineOrchestrator (ThreadPoolExecutor, phases 1-4)
│   │   ├── actor.py              # AssetActor (run_cycle lifecycle)
│   │   └── health.py             # HealthMonitor (validity, drawdown, signal drought)
│   ├── api/
│   │   ├── routes.py             # REST API route handlers (30+ endpoints)
│   │   ├── common.py             # Shared cache, MIME types, vol baselines
│   │   └── handler.py            # HTTP request handler
│   ├── dashboard/                # React SPA (Vite + TypeScript)
│   │   ├── src/components/       # React components
│   │   └── dist/                 # Built frontend
│   ├── entry/                    # Entry optimizer, policy, TP compiler
│   ├── position/                 # Position manager, dynamic SL/TP, scale-out
│   ├── governance/               # Narrative, liquidity, regime, drift
│   ├── execution/                # Paper broker, bridge
│   ├── shadow/                   # Counterfactual replay engine
│   ├── services/                 # Entry, metrics, position, governance, state services
│   ├── attribution/              # Attribution collector
│   ├── replay/                   # WAL-based replay runner
│   ├── ops/                      # Data fetcher, diagnostics, tracer
│   ├── models/                   # Per-asset XGBoost model files
│   ├── config_manager.py         # YAML config loader
│   ├── asset_pnl_controller.py   # Per-asset PnL management
│   └── serve.py                  # Dashboard server entry point
├── scripts/                      # Backtesting, training, scoring, migrations
├── shared/                       # Pluggable strategy interfaces, execution config
├── monitoring/                   # PSI drift, validity state machine
└── monitor_all                   # Entry point script
```

## 7. Go-Live Checklist (Paper Trading → Live)

Before transitioning from paper to live, verify all checks below. 6/7 must pass for go-live.

| # | Check | Target | Source | Criticality |
|---|-------|--------|--------|-------------|
| 1 | Gate override rate | <40% across all assets | `data/monitoring/paper_trade_monitor.csv` — column `gate_overrides` | Hard |
| 2 | Mean confidence | >0.52 for ≥15/18 assets | Monitor CSV — column `mean_confidence` per snapshot | Hard |
| 3 | Signal flips | ≤3/day for ≥15/18 assets | Monitor CSV — column `signal_flips` | Hard |
| 4 | Cross-asset correlation | No unexplained >0.7 | `python scripts/signal_correlation_check.py` | Hard |
| 5 | MT5 errors | Zero across all cycles | `grep ERROR /tmp/paper_trading.log` | Hard |
| 6 | Trades executed | ≥10 across portfolio | MT5 terminal or dashboard trades panel | Hard |
| 7 | SELL_ONLY filter | BUY→FLAT overrides active for 11 assets | `grep "sell-only filter" /tmp/paper_trading.log` | Hard |

**Decision:** 6/7 pass → go live at 50% position size for 2 weeks, then full size if live Sharpe tracks within 0.2 of backtest Sharpe.

**Audit commands:**
```bash
# 1. Gate override rate
python -c "import csv; from collections import Counter; r=csv.DictReader(open('data/monitoring/paper_trade_monitor.csv')); rates=[int(row['gate_overrides'])/int(row['n_assets']) for row in r if row.get('gate_overrides')]; print(f'Mean: {sum(rates)/len(rates):.1%}  Max: {max(rates):.1%}')"

# 2. Mean confidence across days
python -c "import csv; r=csv.DictReader(open('data/monitoring/paper_trade_monitor.csv')); [print(f'{row[\"timestamp\"][:10]}: {row[\"mean_confidence\"]}') for row in r]"

# 3. Signal flips per day
python -c "import csv; r=csv.DictReader(open('data/monitoring/paper_trade_monitor.csv')); [print(f'{row[\"timestamp\"][:10]}: {row[\"signal_flips\"]}') for row in r]"

# 4. MT5 errors
grep -c 'ERROR' /tmp/paper_trading.log

# 5. Trades from dashboard
curl -s http://127.0.0.1:5000/trades.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Trades: {len(d)}')"
```

---

## Appendix: Troubleshooting

| Symptom | Likely Cause | Check |
|---------|-------------|-------|
| Dashboard not loading | Port 5000 in use | `fuser 5000/tcp` |
| Stale prices | yfinance rate limited | `python -c "import yfinance as yf; d=yf.download('BTC-USD',period='1d'); print(d)"` |
| Model file missing | First run or retrain failed | `ls -la paper_trading/models/*.json` |
| All assets showing FLAT with low conf | Macro data stale | Check `data/live/cache/` modification dates |
| Portfolio value not changing | Process not running | `ps aux | grep monitor.py` |
| BTC drawdown > 15% | Normal for BTC (limit is -15%) | Let it run unless RED state persists > 5 days |
| SELL_ONLY asset showing BUY signal | Deferred-entry BUY may bypass sell-only filter | Check `entry_service.py` logs; should be canceled with `sell_only_filter` reason |
| Equity cluster alarm firing | ES/NQ/^DJI all on same side | Recommendation only — no forced flatten. Monitor for correlated risk. |
| JPY cross entering RED state | VIX spike or yield spread inversion | Check VIX level and US-JP 10y spread |
| GC=F showing flat/neutral bias | Real yields not updating on weekends | Normal — gold macro features are daily |
| Dashboard shows CLSD / "weekend — no refresh" | Normal — market is closed | Engine resumes automatically Sun 17:00 ET |
| "Market closed — skipping refresh" in logs | Normal — engine is paused for weekend | No action needed; data is stale but preserved |
| "entry gate blocking" in logs | Normal — cooldown or same-day stop-out lock active after SL | Indicates `_can_enter()` is working; no action unless persists > 24h |
| Clustered SL sequence (6+ same side, same day) | Deferred entry bypassing cooldown (pre-fix) | Should no longer occur after `_can_enter()` gate — file issue if seen |
| State API `market_closed: true` | Engine correctly detected weekend | N/A — server-driven indicator |
| Dashboard polling slower than usual | Intended — hooks reduce refetch rate 4-20x when markets closed | Saves bandwidth; restore normal rate on market open |
