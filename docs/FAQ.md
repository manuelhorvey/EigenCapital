# EigenCapital — Frequently Asked Questions

**Last updated:** 2026-07-05

---

## Configuration & Setup

### How do I switch operating modes?

Edit the active mode in the configuration system. Each mode is defined in a YAML file under `configs/domains/modes/`. To switch:

```bash
# Edit the desired mode file, then restart the engine:
./monitor_all
```

Available modes: `production` ($100K, 8 concurrent, -15% DD), `challenge_ftmo_10k` ($10K, 5 concurrent, -8% DD), `live` ($100K, 6 concurrent, -10% DD).

### Where is the configuration file?

Configuration is stored in the domain tree under `configs/domains/` — organized by concern (risk, portfolio, ML, broker, execution, governance, assets, modes). There is no single monolithic config file. The legacy `configs/paper_trading.yaml` was deleted in Phase 12.7.

### How do I add a new asset to the portfolio?

1. Create `configs/domains/assets/<TICKER>.yaml` with the asset's parameters
2. Add the MT5 symbol mapping in `configs/mt5_symbol_map.yaml`
3. Run validation: `python tools/check_config_schema.py`
4. Train the model: `python scripts/training/retrain_all_fixed.py`

### How do I remove an asset from the portfolio?

1. Remove its YAML file from `configs/domains/assets/`
2. Remove it from `configs/domains/assets/_index.yaml`
3. Move its model to `paper_trading/models/orphaned/`
4. Run `python tools/check_config_schema.py`

---

## Operations

### What should I check each morning?

See the daily procedure in `docs/OPERATIONS.md` (section 1). The key checklist:
- Dashboard is updating with current prices (ConnectionStatus shows **Live**)
- All 22 assets show a signal (BUY/SELL/FLAT) with confidence
- No asset is in RED halt state
- Portfolio drawdown is not approaching -15%
- Narrative is confirmed if Monday morning (check **NARR PENDING** button)

### How do I know if the engine is running correctly?

```bash
curl http://127.0.0.1:5000/ping
# → {"status": "ok"}

# Check engine logs for signal lines on all assets:
# GC: BUY conf=XX% @ $XX.XX
# USDCHF: BUY conf=XX% @ $XX.XX
```

### What does "CLSD" mean on the dashboard?

The market is closed (weekend or after-hours). The engine is in weekend mode — non-eligible assets show stale data. BTCUSD (crypto, `crypto: [0,24]` session tier) continues to refresh at 0.5× allocation multiplier.

### Why does cycle 1 after restart show no trades?

That's the **first-cycle suppression** — a safety feature that suppresses all trading on cold-start cycle 1. Features computed from 200 rows of history differ from steady-state 1-row updates. Trading resumes on cycle 2+.

### What does "bar-jump suppression" mean?

The engine detected a data-source switch (bar count changed by >100, typically MT5→yfinance or vice versa). All trading is suppressed for 60 minutes to allow feature computation to stabilize.

---

## Models & Training

### When do models retrain?

Annually (January 1) by default. You can force a retrain at any time:

```bash
PYTHONPATH=$PYTHONPATH:. python scripts/training/retrain_all_fixed.py
```

### Why is the ensemble disabled?

The regime-conditional ensemble was disabled on 2026-06-20 after walk-forward PnL comparison showed a −3.19R difference vs base-only (p=0.1685, not significant). See ADR-026 for the full decision record. Base model only (`base_weight=1.0`) is the current production configuration.

### How is model probability calibration done?

Raw XGBoost probabilities are binned-calibrated per asset using `BinnedCalibrator` (P1 layer). This reduces Expected Calibration Error (ECE) from ~0.36 to ~0.02 (94.3% reduction). Configured via `calibration.enabled: true` in the config.

### How do I train calibration models?

```bash
PYTHONPATH=$PYTHONPATH:. python scripts/training/train_calibration.py
```

Calibrators are trained from walk-forward signal parquets. Run after parquet regeneration.

---

## Signals & Decisions

### What does "SELL_ONLY" mean?

The model's BUY signal is inverted for 6 assets (CADCHF, EURAUD, EURCHF, GBPCHF, GBPJPY, NZDCHF) — `p_long > 0.5` reliably predicts the wrong direction. The SELL_ONLY filter overrides BUY signals to FLAT for these assets. SELL signals pass through unchanged. This is a permanent architectural limitation — the root cause is unknown and two causal hypotheses (carry, DXY) have been falsified.

### Why does an asset show BUY but no trade is placed?

Possible reasons (checkable in order):
1. **Sell-only filter** — asset is SELL_ONLY (BUY→FLAT)
2. **Price deviation** — current price moved >2% from entry price
3. **Confidence gate** — model confidence below `min_confidence` threshold
4. **Spread gate** — spread exceeds per-class threshold
5. **Session gate** — outside market hours for the asset-class tier
6. **PEK budget** — portfolio notional exceeds `max_leverage × equity`

All blocked entries are logged with the specific gate reason.

### What is the holding period for trades?

Default: 20 bars (vertical barrier) or until TP/SL is hit. The adaptive exit engine may exit earlier via breakeven lock (at 0.5R MFE) or retracement trail (at 0.8R activation). Average holding period is ~9.4 candles.

---

## Risk & Governance

### How is the risk budget calculated?

The Portfolio Execution Kernel (PEK) computes an adaptive risk budget each cycle:
1. `RiskEngineV2` produces a scalar from current drawdown and performance state
2. `PerformanceState` velocity adds an anticipatory scalar [0.5, 1.5]
3. `PortfolioAdmissionController` collects all trade intents → filters → ranks → allocates budget
4. If total notional exceeds `max_leverage × equity × tolerance`, lowest-ranked positions are closed

### What happens when portfolio drawdown reaches -15%?

The circuit breaker triggers — ALL positions are immediately force-closed with reason `portfolio_circuit_breaker`. Signal generation is skipped for that cycle. Trading resumes on subsequent cycles if drawdown recovers.

### How does the validity state machine work?

Each asset has an independent state machine: GREEN (full exposure, 1.0×), YELLOW (reduced, 0.5×), RED (halted, 0.0×). Transitions use hysteresis bands, exponential inertia, and a 5-period persistence lock. Input signals include drawdown, monthly profit factor, signal drought, and confidence drift.

### What is PSI drift and how do I respond?

Population Stability Index measures feature distribution shift against training baseline. Per computed per feature per asset each cycle:
- **NO_DRIFT** (< 0.1): Normal, no action needed
- **MODERATE** (0.1–0.2): Validity penalty applied, monitor
- **SEVERE** (> 0.2): Validity penalty, investigate
- **3+ SEVERE**: Hard halt on the asset

Check `curl http://127.0.0.1:5000/psi.json` or the PSI Drift panel on the dashboard.

### What does "LIQ THIN" / "LIQ STRSD" mean?

Liquidity regime states from the daily OHLCV analysis:
- **LIQ THIN** (yellow badge): Low volume, SL widened +15%, size reduced -15%
- **LIQ STRSD** (red badge): Stress conditions, SL widened +30%, size reduced -30%, asset halted

Check per-asset breakdown via dashboard hover tooltip or `curl http://127.0.0.1:5000/liquidity.json`.

---

## MT5 Bridge

### Can I run the system without MT5?

Yes. The engine falls back to `PaperBroker` (simulated fills) if MT5 is unavailable. All paper trading metrics are still computed. MT5 is only needed for live-order practice on a demo account.

### What does the MT5 bridge do?

The bridge (`paper_trading/ops/mt5_bridge.py`) runs under Wine Python and connects to the MT5 terminal. It receives commands from the engine via TCP (port 9879): place orders, close positions, modify SL/TP, get positions, get prices, get account info.

### How do I know if MT5 is connected?

Check the dashboard header for MT5 status. Or:
```bash
curl http://127.0.0.1:5000/mt5/status.json
```

### Why is MT5 not placing orders?

Common causes:
- Account equity is $107 demo (0.01 lot minimum for forex ≈ $1,150 notional on EURUSD — exceeds position budget)
- Bridge is disconnected (check Wine process)
- `get_current_price()` returned stale data (5s socket timeout)

---

## Development

### How do I run the test suite?

```bash
# Python tests
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/ -v --tb=short -x

# Dashboard tests
cd paper_trading/dashboard && npx vitest run --reporter verbose

# Chaos tests
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/chaos/ -v --tb=short
```

### How do I run the dashboard without the engine?

Start just the dashboard server:
```bash
PYTHONPATH=$PYTHONPATH:. python paper_trading/ops/monitor.py
```

### What linters and checks run in CI?

See the full list in `.github/workflows/ci.yml`. Key checks:
- `ruff check . && ruff format . --check`
- `python tools/check_config_schema.py`
- `PYTHONPATH=$PYTHONPATH:. python tools/doc_drift_check.py`
- `npx tsc -b --noEmit` (dashboard TypeScript)

### Where is the glossary of domain terms?

See `docs/GLOSSARY.md` — 80+ terms organized by category with an acronym quick-reference table.

---

## Troubleshooting

### Dashboard is not loading

```bash
# Check if the server is running
ps aux | grep monitor.py

# Check if port 5000 is in use
fuser 5000/tcp
```

### Prices are stale (>24h)

```bash
# Check yfinance availability
python -c "import yfinance as yf; d=yf.download('EURUSD=X',period='5d'); print(d.empty)"

# Check internet connectivity
ping -c 3 google.com
```

### Model file is missing

```bash
# List model files
ls -la paper_trading/models/*.json

# They are gitignored — you need to train them first:
PYTHONPATH=$PYTHONPATH:. python scripts/training/retrain_all_fixed.py
```

### All assets showing FLAT with low confidence

Macro data may be stale. Check cache file modification dates:
```bash
ls -la data/live/cache/
```
