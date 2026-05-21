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
| Refresh interval | 30 minutes (configurable in `monitor.py`) |
| Retrain frequency | Annual (January 1) |
| Training window | 5-year expanding |

### Assets

| Asset | Weight | Ticker | Drawdown Limit | Vol Scaling | Label |
|-------|--------|--------|----------------|-------------|-------|
| BTC | 20% | BTC-USD | -15% | Yes (target 30%) | tb20 |
| GC=F | 20% | GC=F | -8% | No | fwd60 |
| EURAUD | 22% | EURAUD=X | -8% | No | tb20 |
| NZDJPY | 15% | NZDJPY=X | -6% | No | tb20 |
| CADJPY | 13% | CADJPY=X | -8% | No | tb20 |
| USDCAD | 10% | USDCAD=X | -8% | No | tb20 |

### Halt Parameters (global defaults, overridable per asset)

```
drawdown: -0.08       # Per-asset drawdown limit
monthly_pf: 0.70      # Minimum monthly profit factor
signal_drought: 30    # Max days without a signal (future use)
prob_drift: 0.15       # Max probability distribution drift (future use)
```

---

## 1. Daily Procedure

### Morning Check (before market open, ~08:30 ET)

```
./monitor_all
```

The script:
1. Loads cached model pickles from `paper_trading/models/`
2. Downloads fresh OHLCV data via yfinance
3. Downloads FRED macro data (rate_diff, yields, VIX, DXY)
4. Computes features
5. Runs inference on all three assets
6. Opens/closes positions based on signal vs current position
7. Serves dashboard on port 5000
8. Repeats every 30 minutes

**What to verify on the dashboard:**

- Portfolio total value and daily return are updating
- All six assets show a signal (BUY/SELL/FLAT) with confidence
- Current price is within ~0.5% of market price
- No asset is in halt (check asset cards for RED status)
- Drawdown % is not approaching the per-asset limit

### Log Check

After startup, verify log output shows:
```
BTC: BUY  conf=XX%  @ $XX.XX
GC=F: BUY conf=XX%  @ $XX.XX
EURAUD: SELL conf=XX%  @ $XX.XX
NZDJPY: BUY conf=XX%  @ $XX.XX
CADJPY: FLAT conf=XX% @ $XX.XX
USDCAD: BUY conf=XX%  @ $XX.XX
Portfolio: $XXXXX (XX%)
```

If any asset shows `ERROR`, investigate immediately (see Halt Conditions).

### End of Day (~17:00 ET)

Run once more to capture the closing signal:
```
# If process is still running, signals refresh automatically
# If not, start it: ./monitor_all
```

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
| BTC | tb20 | ~1:1 | 60-80% |
| GC=F | fwd60 | ~1:1 | 55-75% |
| EURAUD | tb20 | ~1:1 | 55-75% |
| NZDJPY | tb20 | ~1:1 | 55-75% |
| CADJPY | tb20 | ~1:1 | 55-75% |
| USDCAD | tb20 | ~1:1 | 55-75% |

**If ratio exceeds 3:1 in either direction**, investigate macro context. A sustained imbalance may indicate:
- A structural regime shift (e.g., persistent tightening)
- Feature drift (PSI > 0.25 on a key feature)
- Data feed issue (stale macro data)

### Drift Check (Manual PSI Monitoring)

Compare current feature distributions against training period:
```python
import pandas as pd
import numpy as np

# Load training features from last retrain
train = pd.read_parquet('data/processed/training_features.parquet')

# Load recent inference features
from paper_trading.data_fetcher import fetch_live, fetch_ref
from scripts.train_all_assets import load_macro_data
macro = load_macro_data()
df = fetch_live('XLF')
ref = fetch_ref('SPY')

# Replicate feature computation and compare distributions
# Train vs inference: mean, std, PSI for each feature
```

**PSI thresholds:**
- `< 0.10`: No drift
- `0.10 - 0.25`: Monitor; log for retrain
- `> 0.25`: Investigate; may trigger halt

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

The system has two independent halt mechanisms:

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

### 3.3 Data Feed Failure

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
| AUDJPY integration | Deferred until post-November (r=0.87 with NZDJPY) | Portfolio evaluation |
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

## Appendix: File Locations

```
Project Root/
├── configs/
│   └── paper_trading.yaml        # Asset config, halt conditions, weights
├── data/
│   ├── live/
│   │   └── state.json            # Current portfolio and asset state
│   └── processed/
│       ├── macro_factors.parquet # FRED macro data
│       └── walkforward_summary.csv  # 30-asset walk-forward ranking
├── paper_trading/
│   ├── engine.py                 # AssetEngine, PaperTradingEngine
│   ├── serve.py                  # HTTP server + dashboard
│   └── models/
│       ├── BTC_model.pkl
│       ├── GC_model.pkl
│       ├── EURAUD_model.pkl
│       ├── NZDJPY_model.pkl
│       ├── CADJPY_model.pkl
│       └── USDCAD_model.pkl
├── scripts/
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
