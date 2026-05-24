# QuantForge — Paper Trading Runbook

Operational procedures for the paper trading system. This document is for the person responsible for monitoring and maintaining the live paper trading instance.

---

## Quick Reference

| Item | Value |
|------|-------|
| Start command | `./monitor_all` |
| Dashboard URL | `http://127.0.0.1:5000` |
| Config file | `configs/paper_trading.yaml` |
| State file | `data/live/state.json` |
| Model pickles | `paper_trading/models/*.pkl` |
| Logs | stdout (redirect to file as needed) |
| Refresh interval | 300s / 5 min (configurable via `QUANTFORGE_REFRESH_INTERVAL` env var) |
| Weekend behavior | Auto-pauses Fri 17:00 ET — Sun 17:00 ET; dashboard stays live with CLSD badge |
| Weekend polling | Reduced to every 120s (state) / 5 min (secondary endpoints) |
| Market hours logic | `paper_trading/market_hours.py` — `is_market_closed()` |
| Retrain frequency | Annual (January 1) |
| Training window | 5-year expanding |
| Hardening guide | `docs/HARDENING_ROADMAP.md` |

### Assets

**Core portfolio (13 assets):**

| Asset | Weight | Ticker | sl_mult | tp_mult | R:R | Scale-out | Label | Regime-tuned |
|-------|--------|--------|---------|---------|:---:|-----------|-------|--------------|
| EURAUD | 12% | EURAUD=X | 0.30 | 1.00 | 1:3.3 | 4-tier | tb20 | yes |
| GC | 13% | GC=F | 0.30 | 1.50 | 1:5.0 | no | fwd60 | yes |
| NZDJPY | 11% | NZDJPY=X | 0.30 | 1.75 | 1:5.8 | 4-tier | tb20 | yes (adaptive_macro + dji_lead_1) |
| CADJPY | 9% | CADJPY=X | 0.30 | 1.25 | 1:4.2 | 4-tier | tb20 | yes (+ dji_lead_1) |
| USDCAD | 8% | USDCAD=X | 0.30 | 1.50 | 1:5.0 | 4-tier | tb20 | yes (+ dji_lead_1) |
| GBPJPY | 8% | GBPJPY=X | 0.30 | 1.25 | 1:4.2 | 4-tier | tb20 | yes (+ dji_lead_1) |
| CHFJPY | 7% | CHFJPY=X | 0.30 | 1.00 | 1:3.3 | no | tb20 | yes |
| AUDJPY | 6% | AUDJPY=X | 0.30 | 1.75 | 1:5.8 | 4-tier | tb20 | yes (+ nzdjpy_lead_3 + dji_lead_1) |
| EURCAD | 5% | EURCAD=X | 0.30 | 1.75 | 1:5.8 | 4-tier | tb20 | yes |
| ^DJI | 5% | ^DJI | 0.30 | 1.50 | 1:5.0 | 4-tier | tb20 | yes |
| GBPUSD | 5% | GBPUSD=X | 0.52 | 1.97 | 1:3.8 | 4-tier | tb20 | no |
| USDJPY | 4% | USDJPY=X | 0.30 | 1.00 | 1:3.3 | no | tb20 | yes (+ gc_lead_1) |
| USDCHF | 4% | USDCHF=X | 0.30 | 1.75 | 1:5.8 | 4-tier | tb20 | yes (+ gc_lead_1) |

**BTC satellite bucket:** 5% AUM cap, vol target 40%, drawdown limit 25%, 5-condition AND gate. Actively managed — when the gate is OPEN the satellite opens a long BTC position with vol-adjusted SL/TP; when the gate CLOSES or SL/TP is hit the position is flattened. Entry price, stop price, target price, and exit reason are logged every cycle and shown on the dashboard.
**SL/TP base values:** Core assets use sl=0.30 universal (research-optimized via sweep across 3 regimes). BTC satellite uses satellite-specific multipliers: `sl_mult=0.58`, `tp_mult=1.51`. SL/TP are computed as `entry × (1 ± vol × multiplier)` where `vol` = EWMA(span=100) of BTC daily log returns (same formula as core assets, matching `AssetEngine._tb_vol`). Model-validity adjustments: YELLOW → tp × 0.85, RED → tp × 0.70. SL unchanged across validity states.
**Dynamic SL/TP ATR Calibration:** ATR-based dynamic barriers auto-calibrated at engine startup to EWM vol using `calibration_scale: 1.2` (expanding barriers by 20% to support higher TP rates).
**Confidence-based SL adjustment (optional):** When `confidence_sl_adjust > 0.0`, SL width tightens as meta-label confidence increases (p=0.9 → sl × (1.0 - adjust), p=0.1 → sl × (1.0 + adjust/2)). Default 0.0 (disabled).
**Scale-Out Strategy:** For assets with scale-out enabled (EURAUD, NZDJPY, CADJPY, AUDJPY, USDCAD, GBPJPY, USDCHF, GBPUSD, EURCAD, DJI), profit-taking is split into 4 equal tiers (25% at 0.25x / 0.50x / 0.75x / 1.00x of original TP multiplier). The stop-loss is moved to breakeven after Tier 1 is filled (`activate_breakeven_after: 0`). Optionally, trailing stop activation can be triggered after a configurable tier (`trailing_after_tier`, default disabled) — see `ScaleOutEngine` in `paper_trading/scale_out.py`.

**Dashboard features:** Per-asset scale-out tier progress visualization (filled vs pending tiers shown as color-coded blocks in AssetCard). SL/TP hit rate gauge bars (GREEN/YELLOW/RED thresholds) in the Trade Outcomes table. PSI Drift panel with per-feature distribution shift scores, trend arrows, and color-coded classification badges. **Satellite card** shows entry price, stop price, target price when position active; SL/TP show `—` when flat; last exit reason (SL_HIT/TP_HIT/GATE_CLOSED) is displayed after each exit.

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
prob_drift: 0.15       # Max confidence drift from expected baseline
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

---

## 1. Daily Procedure

### Morning Check (before market open, ~08:30 ET, Mon–Fri)

```
./monitor_all
```

The script:
1. Loads cached model pickles from `paper_trading/models/`
2. Downloads fresh OHLCV data via yfinance
3. Downloads FRED macro data (rate_diff, yields, VIX, DXY)
4. Computes features
5. Runs inference on all assets
6. Opens/closes positions based on signal vs current position
7. Serves dashboard on port 5000
8. Repeats every refresh interval (default 300s, configurable via `QUANTFORGE_REFRESH_INTERVAL` env var)

**Weekend / after-hours:** The engine auto-detects market closure (Fri after 17:00 ET, all day Sat/Sun). Refresh cycles are skipped — no yfinance data pulls, no signal generation, no SL/TP checks. The dashboard stays live showing the last pre-close state with a yellow **CLSD** badge. Normal operation resumes at the next scheduled refresh after Sun 17:00 ET.

A quick health check via `/ping`:
```bash
curl http://127.0.0.1:5000/ping
# → {"status": "ok"}
```

**What to verify on the dashboard:**

- Portfolio total value and daily return are updating
- All 13 core assets show a signal (BUY/SELL/FLAT) with confidence
- **BTC Satellite card**: check gate state (OPEN/CLOSED), position state (ACTIVE/FLAT), entry/SL/TP prices, and exit reason after each exit
- Current price is within ~0.5% of market price
- No asset is in halt (check asset cards for RED status)
- Per-asset drawdown % is not approaching per-asset limits
- Portfolio drawdown value is not approaching -15% circuit breaker threshold
- Market status badge shows **OPEN** (green) during trading hours, **CLSD** (yellow) on weekends
- **LAST** timestamp in the header shows when signals were last refreshed
- **Scale-out tiers** on open positions: check filled vs pending tier blocks in AssetCard
- **SL/TP gauge bars** in Trade Outcomes: GREEN TP rate (≥25%), GREEN SL rate (≤50%), GREEN flip rate (≤15%)
- **Narrative badge**: check overall_regime indicator (red/yellow/green/grey) and stale flag; check for **NARR PENDING** button or **NARR ERR** badge
- **Liquidity badge**: check for **LIQ THIN** (yellow) or **LIQ STRSD** (red); hover for per-asset breakdown
- **PSI Drift panel**: check for any MODERATE (amber) or SEVERE (red) feature classifications; note trend arrows — SEVERE + INCREASING arrow is a genuine drift signal, SEVERE + STABLE may be a data hiccup; look for **PSI HALT** badge on halted assets

### Log Check

After startup (Mon–Fri during market hours), verify log output shows:
```
EURAUD: BUY conf=XX% @ $XX.XX
GC: SELL conf=XX% @ $XX.XX
NZDJPY: BUY conf=XX% @ $XX.XX
CADJPY: FLAT conf=XX% @ $XX.XX
AUDJPY: BUY conf=XX% @ $XX.XX
USDCAD: SELL conf=XX% @ $XX.XX
GBPJPY: BUY conf=XX% @ $XX.XX
USDJPY: FLAT conf=XX% @ $XX.XX
USDCHF: SELL conf=XX% @ $XX.XX
GBPUSD: BUY conf=XX% @ $XX.XX
CHFJPY: FLAT conf=XX% @ $XX.XX
EURCAD: SELL conf=XX% @ $XX.XX
^DJI: BUY conf=XX% @ $XX.XX
BTC satellite: gate=OPEN/CLOSED, position=ACTIVE/FLAT, value=XXXX
Portfolio: $XXXXX (XX%)
```

If any asset shows `ERROR`, investigate immediately (see Halt Conditions). If the satellite shows `exit=SL_HIT` or `exit=TP_HIT`, this is normal — SL/TP are real working levels. Verify the SL/TP prices make sense relative to the entry price and current volatility.

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

| Asset | Label | BUY/SELL Ratio | Mean Confidence |
|-------|-------|----------------|-----------------|
| EURAUD | tb20 | ~1:1 | 55-75% |
| GC | fwd60 | ~1:1 | 55-75% |
| NZDJPY | tb20 | ~1:1 | 55-75% |
| CADJPY | tb20 | ~1:1 | 55-75% |
| CHFJPY | tb20 | ~1:1 | 55-75% |
| EURCAD | tb20 | ~1:1 | 55-75% |
| AUDJPY | tb20 | ~1:1 | 55-75% |
| USDCAD | tb20 | ~1:1 | 55-75% |
| GBPJPY | tb20 | ~1:1 | 55-75% |
| ^DJI | tb20 | ~1:1 | 55-75% |
| USDJPY | tb20 | ~1:1 | 55-75% |
| USDCHF | tb20 | ~1:1 | 55-75% |
| GBPUSD | tb20 | ~1:1 | 55-75% |

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
ls -la paper_trading/models/*.pkl
```

Check the pickle modification dates are within the expected retrain window.

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
| Signal drought | No signal for 30 days | (Reserved — not yet implemented) |
| Prob drift | Confidence drift > 0.15 | (Reserved — not yet implemented) |

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
- Hover tooltip shows per-asset breakdown: `EURAUD: THIN sl=1.15x size=0.85x`

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

### 3.7 Data Feed Failure

If yfinance returns empty or stale data for any ticker:

**Symptoms:**
- `ERROR - No live data for XLF` in logs
- Dashboard shows stale prices (>24h old)
- Missing signals for that asset

**Response:**
1. Verify yfinance availability: `python -c "import yfinance as yf; d=yf.download('XLF',period='5d'); print(d.empty)"`
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
- NEUTRAL class probability < 0.15 (model is not becoming indecisive)

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
| AUDJPY — RESOLVED | Added to live portfolio (5/5 WF windows, Sharpe 2.62). Correlated with NZDJPY (r=0.87) but diversifies JPY carry exposure at 6% weight. | — |
| Weekly timeframe models | Lower frequency for macro-only signals | Feature engineering |
| Meta-labeling filter | Second-stage trade filter to reduce trade count | More training data |
| Sector rotation extension | Apply driver atlas to other equity sectors | Paper trading results |
| Regime classifier V2 | Reduce volatility gate false positives | More regime diversity in data |

### P2 — Future Research

| Item | Description |
|------|-------------|
| Intraday models | 1-hour bars for FX (requires COT + tick data) |
| Options overlay | Covered call/cash-secured put on XLF positions |
| Crypto expansion | ETH, SOL with momentum_crypto driver cluster |
| Cross-asset feature transfer | Transfer learning between driver clusters |
| LLM-based sentiment | Macro news sentiment as feature for FX |

---

## 6. Execution Physics and Sizing (Hardening)

Live paper trading applies **spread + impact** on entries and exits via `ExecutionBridge` (`paper_trading/execution_bridge.py`). Config is in `configs/paper_trading.yaml`:

```yaml
execution_defaults:
  base_spread_bps: 0.5
  spread_vol_slope: 2.0
  impact_model: square_root
  impact_coeff: 0.1

assets:
  NZDJPY:
    regime_sizing: true      # vol target scales by regime
    adaptive_macro: true     # only if model pickle has macro_head (HybridEnsemble)
    execution_config:
      base_spread_bps: 2.0
      avg_daily_volume: 300000000
```

**Volatility dashboard** (`/volatility.json`) compares live vol to `vol_baselines` in the same YAML file.

**Decision payload** may include `macro_weight` when adaptive macro is active.

**Research / validation:** see `docs/HARDENING_ROADMAP.md` for extended history, lead-lag, and pytest targets.

---

## Appendix: File Locations

```
Project Root/
├── configs/
│   └── paper_trading.yaml        # Assets, halt, vol_baselines, execution_config
├── data/
│   ├── live/
│   │   └── state.json            # Current portfolio and asset state
│   ├── research/
│   │   ├── lead_lag_matrix.parquet
│   │   ├── lead_lag_edges.yaml
│   │   └── survival_*.json       # Baseline vs extended survival exports
│   ├── raw/historical_extended/  # 2000+ OHLCV (after backfill)
│   └── processed/
│       ├── macro_factors.parquet # FRED macro data
│       └── walkforward_summary.csv  # 30-asset walk-forward ranking
├── paper_trading/
│   ├── engine.py                 # PaperTradingEngine + PaperBroker
│   ├── execution_bridge.py       # Slippage-aware fills for AssetEngine
│   ├── market_hours.py           # Weekend detection: is_market_closed()
│   ├── serve.py                  # HTTP server + dashboard
│   └── models/
│       ├── BTC_model.pkl
│       ├── GC_model.pkl
│       ├── EURAUD_model.pkl
│       ├── NZDJPY_model.pkl
│       ├── CADJPY_model.pkl
│       └── USDCAD_model.pkl
├── scripts/
│   ├── run_extended_history_pipeline.py  # Backfill + extended_predictions stubs
│   ├── train_all_assets.py       # 30-asset training pipeline
│   ├── walk_forward_all.py       # Walk-forward for all assets
│   ├── cadjpy_walk_forward.py    # CADJPY-specific fwd60 validation
│   └── gc_walk_forward.py        # GC=F-specific fwd60 validation
├── risk/
│   └── position_sizing.py        # Volatility-scaled sizing
├── monitoring/
│   └── validity_state_machine.py # GREEN/YELLOW/RED state machine
└── monitor_all                    # Entry point script
```

## Appendix: Troubleshooting

| Symptom | Likely Cause | Check |
|---------|-------------|-------|
| Dashboard not loading | Port 5000 in use | `fuser 5000/tcp` |
| Stale prices | yfinance rate limited | `python -c "import yfinance as yf; d=yf.download('BTC-USD',period='1d'); print(d)"` |
| Model pickle missing | First run or retrain failed | `ls -la paper_trading/models/` |
| All assets showing FLAT with low conf | Macro data stale | Check `data/processed/macro_factors.parquet` modification date |
| Portfolio value not changing | Process not running | `ps aux | grep monitor.py` |
| BTC drawdown > 15% | Normal for BTC (limit is -15%) | Let it run unless RED state persists > 5 days |
| NZDJPY entering RED state | VIX spike or yield spread inversion | Check VIX level and US-JP 10y spread |
| GC=F showing flat/neutral bias | Real yields not updating on weekends | Normal — gold macro features are daily |
| Dashboard shows CLSD / "weekend — no refresh" | Normal — market is closed | Engine resumes automatically Sun 17:00 ET |
| "Market closed — skipping refresh" in logs | Normal — engine is paused for weekend | No action needed; data is stale but preserved |
| State API `market_closed: true` | Engine correctly detected weekend | N/A — server-driven indicator |
| Dashboard polling slower than usual | Intended — hooks reduce refetch rate 4-20x when markets closed | Saves bandwidth; restore normal rate on market open |
