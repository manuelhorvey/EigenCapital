# EigenCapital — Paper Trading Runbook

Operational procedures for the paper trading system. This document is for the person responsible for monitoring and maintaining the live paper trading instance.

---

## Quick Reference

| Item | Value |
|------|-------|
| Start command | `./monitor_all` |
| Dashboard URL | `http://127.0.0.1:5000` |
| Config file | `configs/paper_trading.yaml` |
| `calibration.enabled` | `true` — BinnedCalibrator applied per inference, reduces ECE 0.36→0.02 |
| `portfolio.weight_method` | `factor_constrained_v2` — active weight strategy (P0, hard linear constraints) |
| `kelly.enabled` | `false` — P2 Kelly sizing disabled pending live data |
| Active mode | `production` (config: `mode:` in `configs/paper_trading.yaml`) |
| Switch mode | Edit `mode:` key in config and restart engine |
| PEK admission event | Logged as `PEK_BUDGET_OVERRUN` + `PEK_BUDGET_CLOSE` — check engine logs |
| PEK dashboard state | `state.json → portfolio → admission` (n_intents, n_admitted, n_rejected, admitted[], rejected[]) |
| State file (JSON) | `data/live/state.json` |
| State store (SQLite) | `data/live/state.db` (6 tables: trades, attribution, shadow_trades, confidence_buckets, equity_history, strategy_metadata) |
| Model files | `paper_trading/models/*.json` (base), `models/regime/*.json` (regime) |
| Logs | stdout (redirect to file as needed) |
| Refresh interval | 60s (configurable via `EIGENCAPITAL_REFRESH_INTERVAL` env var) |
| Weekend behavior | `weekend_eligible` assets (e.g. BTCUSD with `crypto: [0,24]` session tier) run 24/7 at 0.5× allocation multiplier; non-eligible assets pause and show stale data |
| Weekend polling | Normal 60s for eligible assets; reduced to every 120s (state) / 5 min (secondary) for stale assets |
| Market hours logic | `paper_trading/ops/market_hours.py` — `is_market_closed()` |
| Retrain frequency | Annual (January 1) |
| Training window | 5-year expanding |
| Feature build window | 500d (inference truncation validates and trims to 250d for XGBoost hot path) |
| Hardening history | `docs/archive/research_system_v1/HARDENING_ROADMAP.md` |
| Benchmarks | `benchmarks/README.md` (reference: 1.63s warm p50 for 15 assets, 8 workers) |

### Assets

**Core portfolio (22 assets promoted from walk-forward screening):**

Each asset uses risk-parity allocation with per-asset sl_mult, tp_mult, and max_depth calibrated via walk-forward optimization.

**2026-07-04:** BTCUSD (weekend-eligible, crypto: [0,24]) and 4 JPY crosses (AUDJPY, NZDJPY, GBPJPY, USDJPY) added.

**2026-06-22:** GBPUSD promoted (walk-forward IC 0.186, HR 0.371, pt_sl=(1.97, 0.52) → R:R=3.79).

**2026-06-20:** AUDNZD, EURUSD, AUDCHF, GBPNZD removed (directional instability). USDCAD and NZDUSD halved from 5%→2.5%.

| Asset | Ticker | Allocation | sl_mult | tp_mult | max_depth |
|---|---|---|---|---|---|---|
| GC | GC=F | 7.0% | 1.00 | 4.00 | 2 |
| USDCHF | USDCHF=X | 4.0% | 0.85 | 3.00 | 4 |
| USDCAD | USDCAD=X | 2.5% | 1.30 | 3.90 | 5 |
| GBPCAD | GBPCAD=X | 5.0% | 1.45 | 4.34 | 2 |
| NZDCAD | NZDCAD=X | 5.0% | 1.83 | 5.48 | 2 |
| NZDUSD | NZDUSD=X | 2.5% | 1.29 | 3.87 | 5 |
| GBPAUD | GBPAUD=X | 5.0% | 1.00 | 3.00 | 3 |
| NZDCHF | NZDCHF=X | 7.0% | 1.00 | 4.00 | 2 |
| CADCHF | CADCHF=X | 5.0% | 1.00 | 4.00 | 2 |
| AUDUSD | AUDUSD=X | 4.0% | 1.41 | 4.24 | 2 |
| EURCHF | EURCHF=X | 5.0% | 1.00 | 3.00 | 4 |
| EURCAD | EURCAD=X | 2.0% | 0.71 | 2.12 | 3 |
| EURNZD | EURNZD=X | 3.0% | 1.12 | 3.36 | 3 |
| GBPCHF | GBPCHF=X | 3.0% | 0.82 | 2.45 | 2 |
| GBPUSD | GBPUSD=X | 4.0% | 0.52 | 1.97 | 2 |
| EURAUD | EURAUD=X | 1.0% | 0.54 | 1.77 | 2 |
| ^DJI | ^DJI | 2.0% | 0.50 | 4.00 | 3 |
| BTCUSD | BTC-USD | 2.0% | 0.58 | 1.51 | 3 |
| AUDJPY | AUDJPY=X | 2.0% | 0.52 | 2.01 | 2 |
| NZDJPY | NZDJPY=X | 2.0% | 0.51 | 2.02 | 2 |
| GBPJPY | GBPJPY=X | 2.0% | 0.50 | 2.22 | 2 |
| USDJPY | USDJPY=X | 2.0% | 0.52 | 1.97 | 2 |

**Total allocation: varies** (factor_constrained_v2 adjusts dynamically)

**Backtest performance (pre-leak-fix baseline, 5-year: 2021–2025):** PF 1.908, avgR +0.268, 2383 trades.
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
> **Note:** These keys are nested under `execution.governance.` in the YAML (e.g., `execution.governance.narrative_config.min_confidence`).

| Key | Default | Description |
|-----|---------|-------------|
| `narrative_config.enabled` | true | Enable weekly macro narrative |
| `narrative_config.geopol_sl_widen_pct` | 10 | SL widen % on geopol risk |
| `narrative_config.risk_off_size_reduce_pct` | 20 | Size reduce % on risk_off |
| `narrative_config.min_confidence` | 0.6 | Min LLM confidence |
| `narrative_config.auto_confirm_deadline_hour` | 12 | Auto-confirm deadline (ET) |
| `liquidity_config.volume_z_thin_threshold` | -1.5 | Volume z → THIN |
| `liquidity_config.volume_z_stressed_threshold` | -3.0 | Volume z → STRESSED |
| `liquidity_config.amihud_high_threshold` | 1.5 | Amihud z → THIN |
| `liquidity_config.amihud_stressed_threshold` | 4.0 | Amihud z → STRESSED |
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
   min_confidence: 55.0    # Skip entry if model confidence < 55.0%
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

## Mode Configuration

The engine supports three operational modes via the `mode:` key in `configs/paper_trading.yaml`:

| Mode | Capital | Max Risk/Trade | Max Concurrent | DD Limit | Use Case |
|------|---------|---------------|----------------|----------|----------|
| `production` | $100K | 2.0% | 8 | -15% | Standard paper trading |
| `challenge_ftmo_10k` | $10K | 3.0% | 5 | -8% | FTMO 10K challenge |
| `live` | $100K | 3.0% | 6 | -10% | Live funded account |

Mode overrides are merged at config load time. See `configs/paper_trading.yaml` → `modes:` for full definitions.

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
6. Applies decision pipeline stages (22 stages: first-cycle suppression → bar-jump → store metadata → update MAE/MFE → resolve signal → risk-off → VIX gate → sell-only filter → spread gate → session gate → ADX entry gate → confidence gate → hysteresis → meta-label advisory → regime bar counter → conviction gate → kelly sizing → manage position [includes profit lock] → build artifacts → route execution → poll deferred → update prob history)
7. Routes through 15 governance layers + HealthMonitor (circuit breaker, VaR/CVaR, equity cluster alarm) + RecoveryScheduler
8. Opens/closes positions based on signal vs current position (MT5 bridge + paper)
9. Serves dashboard on port 5000
10. Repeats every refresh interval (default 60s, configurable via `EIGENCAPITAL_REFRESH_INTERVAL` env var)

**Signal logging:** The `scripts/ops/monitor_paper_trading.py` script polls the dashboard every 6 hours
and appends a CSV row to `data/monitoring/paper_trade_monitor.csv`. Use it for daily signal checks:

```bash
python scripts/ops/monitor_paper_trading.py
```

**Weekend / after-hours:** The engine auto-detects market closure (Fri after 17:00 ET, all day Sat/Sun). For non-eligible assets, refresh cycles are skipped — no yfinance data pulls, no signal generation, no SL/TP checks. For `weekend_eligible` assets (BTCUSD), filtered cycles continue at 0.5× position multiplier. The dashboard shows a **CLSD** badge for non-eligible assets; BTCUSD continues live data. Normal operation for all assets resumes at the next scheduled refresh after Sun 17:00 ET.

A quick health check via `/ping`:
```bash
curl http://127.0.0.1:5000/ping
# → {"status": "ok"}
```

**What to verify on the dashboard (use the anchor nav bar to jump between sections):**

- Portfolio total value and daily return are updating (trend arrows on metric cards show direction)
- All 16 assets show a signal (BUY/SELL/FLAT) with confidence — click column headers in the Signals table to sort by confidence descending
- Current price is within ~0.5% of market price
- No asset is in halt (check asset cards for RED status)
- Per-asset drawdown % is not approaching per-asset limits
- Portfolio drawdown value is not approaching -15% circuit breaker threshold
- After restart: cycle 1 shows `first-cycle suppression` in logs (normal), trades resume cycle 2+
- After MT5 reconnect: check for `bar-jump suppression` log — suppresses ~60min if bar count changed >100 (normal after source switch)
- Risk-off conditions: if VIX>0 & SPX<0, expect AUDUSD showing `risk-off suppression — holding flat` (validated behavior)
- Sell-only filter: 3 SELL_ONLY assets (CADCHF, NZDCHF, EURAUD) will show `sell-only filter — suppressing BUY signal` for BUY signals, holding flat instead
- Equity cluster alarm: removed 2026-07-01 (ES/NQ/^DJI no longer in portfolio — see `paper_trading/orchestrator/health.py:105`). Historical `equity_cluster_all_*` log lines reference retired assets.
- Spread gate observe mode: in first 720 cycles (~6h), check for `spread gate would block` logs; after observation window, `spread gate blocked entry` is expected for high-spread conditions
- Market status badge shows **OPEN** (green) during trading hours, **CLSD** (yellow) for non-eligible assets on weekends (BTCUSD continues live)
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

After startup (Mon–Fri during market hours), verify log output shows signal lines for all 16 assets:
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

After 17:00 ET on Friday, the engine enters weekend mode. For non-eligible assets, refresh pauses until Sunday 17:00 ET. For `weekend_eligible` assets (BTCUSD), the engine continues running filtered cycles at 0.5× position multiplier (configurable via `weekend_allocation_multiplier`). The dashboard shows a CLSD badge for non-eligible assets; BTCUSD continues to display live data.

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

All 16 assets should show a balanced BUY/SELL ratio (~1:1) with mean confidence in the 55-75% range. For the 3 SELL_ONLY assets, expect FLAT to dominate BUY (BUY signals are overridden to FLAT). Deviations warrant investigation of the specific asset's governance state and recent market conditions.

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
cd /home/manuelhorveydaniel/Projects/Quorrin
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

**`SIZING <asset>: eff_cap=... scalar=... dd=... pos_cap=... risk_cap=... -> final_not=... qty=...`**

Decomposed factors (paper sizing attribution):
- `eff_cap` — effective capital (base × min(growth, 3×))
- `scalar` — composite size scalar (position_size × exposure × kelly × governance × meta combined)
- `dd` — drawdown taper multiplier
- `pos_cap` — max_position_pct_of_equity cap (absolute USD)
- `risk_cap` — max_risk_per_trade_pct cap (absolute USD)
- `final_not` — final notional after all caps
- `qty` — final quantity

**`MT5_SIZING <asset>: equity=... dd=... kelly=... max_pct=... risk_cap=... min_viable=... -> final_not=... base_to_acc=... qty=...`**

Same decomposed factors for MT5, sized against real broker equity. Includes `kelly` scalar and `base_to_acc` ratio (MT5 notional / account equity).

**Guardrail skip reasons:**
- `risk cap would shrink position below min viable` — risk cap clipped below min_viable_position_pct
- `leverage budget exhausted` — portfolio leverage pool drained
- `below min volume` — MT5 qty converts to 0 lots (below broker min_volume)

### 3.8 Data Feed Failure

If yfinance returns empty or stale data for any ticker:

**Symptoms:**
- `ERROR - No live data for <ticker>` in logs (e.g., AUDUSD=X)
- Dashboard shows stale prices (>24h old)
- Missing signals for that asset

**Response:**
1. Verify yfinance availability: `python -c "import yfinance as yf; d=yf.download('EURUSD=X',period='5d'); print(d.empty)"`
2. Check internet connectivity
3. If yfinance is down, the engine will continue running but cannot generate new signals
4. If the outage exceeds one trading day, consider whether to halt

---

---

## Related Documents

| Document | Contents |
|----------|----------|
| `docs/MONITORING.md` | Prometheus metrics, Grafana, alerting |
| `docs/TESTING.md` | Test framework, coverage targets, key patterns |
| `docs/API.md` | All HTTP endpoints |
| `docs/SYSTEM_OVERVIEW.md` | Architecture, feature engineering, sizing chain |
| `docs/GOVERNANCE.md` | Governance layers, halt conditions |
| `AGENTS.md` | Go-live checklist, six-month evaluation, real capital framework |

---

## Troubleshooting

| Symptom | Likely Cause | Check |
|---------|-------------|-------|
| Dashboard not loading | Port 5000 in use | `fuser 5000/tcp` |
| Stale prices | yfinance rate limited | `python -c "import yfinance as yf; d=yf.download('EURUSD=X',period='1d'); print(d)"` |
| Model file missing | First run or retrain failed | `ls -la paper_trading/models/*.json` |
| All assets showing FLAT with low conf | Macro data stale | Check `data/live/cache/` modification dates |
| Portfolio value not changing | Process not running | `ps aux | grep monitor.py` |
| Portfolio drawdown > 15% | Normal during volatile periods (limit is -15%) | Let it run unless RED state persists > 5 days |
| SELL_ONLY asset showing BUY signal | Deferred-entry BUY may bypass sell-only filter | Check `entry_service.py` logs; should be canceled with `sell_only_filter` reason |
| Position concentration alert | >75% of open positions on same side | Recommendation only — monitor dashboard `position_concentration` field |
| JPY cross entering RED state | VIX spike or yield spread inversion | Check VIX level and US-JP 10y spread |
| GC=F showing flat/neutral bias | Real yields not updating on weekends | Normal — gold macro features are daily |
| Dashboard shows CLSD for some assets | Normal — those assets are not `weekend_eligible` | BTCUSD continues to refresh; stale assets resume Sun 17:00 ET |
| "Market closed — skipping refresh" in logs | Normal — engine is in weekend mode for non-eligible assets | No action needed; BTCUSD continues 24/7 |
| "entry gate blocking" in logs | Normal — cooldown or same-day stop-out lock active after SL | Indicates `_can_enter()` is working; no action unless persists > 24h |
| Clustered SL sequence (6+ same side, same day) | Deferred entry bypassing cooldown (pre-fix) | Should no longer occur after `_can_enter()` gate — file issue if seen |
| State API `market_closed: true` | Engine detected market closed; filtered cycle running for eligible assets | N/A — server-driven indicator |
| Dashboard polling slower than usual | Intended — hooks reduce refetch rate 4-20x when markets closed | Saves bandwidth; restore normal rate on market open |

### PEK Budget Overrun

When `PEK_BUDGET_OVERRUN` appears in logs:
1. The PEK admission controller determined total portfolio notional exceeds `max_leverage × equity`
2. Lowest-ranked positions were automatically closed — check `PEK_BUDGET_CLOSE` log lines for which assets
3. Verify in dashboard: `state.json → portfolio → admission` shows `n_admitted` vs `n_rejected`
4. No manual action required — the system self-corrects
