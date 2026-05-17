# QuantForge — System Overview

High-level architecture, component responsibilities, and data flow for the QuantForge quantitative trading framework.

---

## Architecture Diagram

```
Raw Data Layer                  Feature Layer                Model Layer
┌──────────────┐    ┌─────────────────────────┐    ┌─────────────────────┐
│ yfinance     │    │ base_features.py         │    │ HybridRegimeEnsemble│
│ OHLCV daily  │───▶│ regime_features.py       │───▶│ ├─ Global backbone  │
│ FRED macro   │    │ structural_features.py   │    │ ├─ Regime experts   │
│ (rate_diff,  │    │ interaction_features.py  │    │ └─ Macro expert     │
│  yield_curve)│    │ macro features (separate)│    │   (protected 0.45)  │
└──────────────┘    └─────────────────────────┘    └─────────┬───────────┘
                                                             │
                      Signal Layer                 Regime Layer │
              ┌────────────────────────┐    ┌──────────────────┐│
              │ RegimeAwareSignalGen   │◀───│ RegimeClassifier ││
              │ ├─ Threshold 0.45      │    │ KER+ADX+vol     ││
              │ └─ Confidence = max(P) │    │ TREND/RANGE/    ││
              └───────────┬────────────┘    │ VOLATILE/NEUTRAL││
                          │                 └──────────────────┘│
                          │                                      │
              ┌───────────▼──────────────────────────────────────┘
              │
              ▼
    ┌─────────────────────────────────────────────────────────┐
    │                 Validity State Machine                   │
    │  GREEN (1.0) ←→ YELLOW (0.5) ←→ RED (0.0)              │
    │  Hysteresis + temporal smoothing + regime lock          │
    └─────────────────────────┬───────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────┐
    │              Paper Trading Engine                        │
    │  3x AssetEngine (XLF 40%, BTC 35%, NZDJPY 25%)          │
    │  ├─ Live inference every 30 min                          │
    │  ├─ Vol-scaled position sizing                          │
    │  ├─ SL/TP management                                    │
    │  └─ PnL tracking (state.json)                           │
    └─────────────────────────┬───────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────┐
    │              Web Dashboard (port 5000)                   │
    │  Flask/SocketIO + HTML/CSS/JS                            │
    │  ├─ Portfolio summary                                   │
    │  ├─ Per-asset signal cards                              │
    │  ├─ Live execution log                                  │
    │  ├─ Performance metrics                                 │
    │  └─ Validity & regime monitors                          │
    └─────────────────────────────────────────────────────────┘
```

---

## Component Responsibilities

### Data Layer (`data/`)

| Component | File | Responsibility |
|-----------|------|---------------|
| Downloader | `data/loaders/downloader.py` | Daily OHLCV via yfinance |
| Macro Loader | `data/loaders/macro_loader.py` | FRED data — rate_diff, yields, DXY, VIX |
| Weekly Pipeline | `data/weekly_pipeline.py` | Weekly resample (W-FRI), full feature pipeline |
| Live State | `data/live/` | Runtime engine state: state.json, history.parquet |

### Feature Engineering (`features/`)

Features are computed independently per module and concatenated by common index. Each module returns a DataFrame that can be included or excluded per asset.

| Module | Key Features | Used By |
|--------|-------------|---------|
| base | EMA spreads, ADX, MACD, RSI, Bollinger Z-score | All models |
| regime | Hurst exponent, KER, ADX, vol_zscore, compression | Regime classifier |
| structural | Price slope, curvature, path efficiency, skew, kurtosis | Research only |
| interaction | Regime contrast, entropy, transition risk | Research only |
| macro (loader) | rate_diff, dxy_mom, yield_slope, yield_delta | Macro expert head |

### Model Layer (`models/`)

**HybridRegimeEnsemble** (`models/hybrid_ensemble.py`)
- Global backbone: XGBoost (max_depth=2, lr=0.03, 100 trees) — trained on all features
- Regime-specific experts: Separate XGBoost (max_depth=3) per regime — trained on regime-conditional data
- Macro expert head: XGBoost (max_depth=2, heavy regularization) — trained on macro features only
- Blend: `regime_blend = 0.4 * global + 0.6 * expert`, then `final = 0.45 * macro + 0.55 * regime_blend`
- Recency-weighted training samples (linear decay 1.0 → 0.5)
- Regime-weighted sample weights (TREND=1.0, RANGE=0.8, VOLATILE=0.6, NEUTRAL=0.5)

**RegimeClassifier** (`models/regime/regime_classifier.py`)
- TREND score: KER × 1.3 × 0.45 + (ADX / 45) × 0.55
- RANGE score: (1 - KER × 1.8) × 0.35 + (1 - ADX / 30) × 0.35 + (1 - compression) × 2.0 × 0.3
- VOLATILE gate: vol_zscore > 1.35 OR compression > 1.45 (structural priority, overwrites probabilistic)
- NEUTRAL: softmax confidence < 0.45 (catch-all)
- Smoothing: 10-bar rolling mode with persistence lock

### Signal Layer (`signals/`)

**RegimeAwareSignalGenerator**
- Receives blended probabilities from the ensemble (3-class: BUY/NEUTRAL/SELL)
- Applies confidence threshold (0.475 research, 0.45 engine)
- Returns: signal direction, confidence, regime context
- Stateless — regime routing happens in the ensemble, not here

### Risk & Monitoring (`risk/`, `monitoring/`)

**ValidityStateMachine** (`monitoring/validity_state_machine.py`)
- Input: validity score (composite of model confidence, feature drift, market conditions)
- Output: state (GREEN/YELLOW/RED) with capital allocation (1.0/0.5/0.0)
- Hysteresis bands: GREEN entry 0.70, exit 0.60; YELLOW entry 0.45, exit 0.40; RED entry 0.40, exit 0.50
- Exponential decay smoothing (α=0.7, β=0.3)
- Regime persistence lock (minimum 5 periods before transition allowed)
- Capital allocation is stepped, not continuous — makes state auditable

**Position Sizing** (`risk/position_sizing.py`)
- Base dollar risk × regime multiplier
- Engine adds volatility scalar (target_vol=0.30, cap=1.0) for BTC
- Triple-barrier volatility used for SL/TP placement

### Execution (`paper_trading/`)

**AssetEngine** (per-asset instance)
- Loads serialized model pickle
- Fetches live data (yfinance)
- Runs inference → signal → confidence
- Manages position: entry, SL/TP, PnL tracking
- Updates live state (history.parquet, state.json)

**PaperTradingEngine** (orchestrator)
- Manages 3 AssetEngine instances (XLF, BTC, NZDJPY)
- Collects per-asset state into portfolio view
- Runs every 30 minutes (configurable)
- Exposes state via JSON for dashboard

**Web Dashboard** (`paper_trading/serve.py`)
- Zero-dependency (stdlib SimpleHTTPRequestHandler)
- Single-file HTML/CSS/JS with dark theme
- Auto-refresh every 30 seconds
- Displays: portfolio summary, signal cards, PnL, metrics, validity state

### Validation (`backtests/`)

**WalkForwardValidator**
- Expanding window (all data up to year N-1)
- Default: 5yr train / 1yr test / 1yr step
- Bootstrap p < 0.10 deployment gate (10,000 permutations)
- Metrics: PF, Sharpe, win rate, expectancy, max DD, CAGR
- 4/6 windows must pass gate for asset deployment

### Configuration (`configs/`)

YAML configs define per-asset parameters:
- Asset ticker, allocation weight, features
- Halt conditions (drawdown limits per asset)
- Retrain frequency (annual)
- Volatility scaling toggle
- Per-asset model parameters (overrides defaults)

---

## Data Flow

### Research Pipeline

```
OHLCV (daily) ──▶ weekly_pipeline.py ──▶ Feature engineering ──▶ Labeling
     │                                                              │
     └─── Macro data (FRED) ───▶ Align to price index              │
                                                                   ▼
                                                   Walk-forward validation
                                                         │
                                                    Bootstrap gate
                                                         │
                                                    Model serialization
                                                         │
                                                    Paper trading ready
```

### Paper Trading Pipeline

```
yfinance data (every 30 min) ──▶ Feature computation (live)
                                      │
                                 Load model pickle
                                      │
                                 Inference (XGBoost predict_proba)
                                      │
                                 Signal + Confidence (> 0.45?)
                                      │
                                 Validity state machine check
                                      │
                                 Position management (entry/SL/TP)
                                      │
                                 Update state.json ──▶ Dashboard
```

---

## Key Entry Points

| Action | Command/File |
|--------|-------------|
| Run walk-forward research | `python equity/walk_forward_xlf.py` |
| Start paper trading + dashboard | `./monitor_all` |
| Dashboard URL | `http://127.0.0.1:5000` |
| Run tests | `make test` |
| Run full test suite with coverage | `make test-cov` |
| CI pipeline | `.github/workflows/ci.yml` |
| Daily data refresh | `data/weekly_pipeline.py` |

---

## Configuration Reference

**`configs/paper_trading.yaml`:**
- `capital: 100000` — Starting capital
- `position_size: 0.95` — Max position fraction
- Per-asset: ticker, weight, features, drawdown limits, halt conditions
- `retrain_freq: annual` — Model retraining frequency
- `target_vol: 0.30` — Annualized target volatility for position scaling

**Environment:**
- `PYTHONPATH=.:$PYTHONPATH` — Required for module imports
- `.venv/` — Python virtual environment
- `paper_trading/models/*.pkl` — Serialized models
