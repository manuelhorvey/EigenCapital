# QuantForge — System Overview

High-level architecture, component responsibilities, and data flow for the QuantForge quantitative trading framework.

---

## Architecture Diagram

```mermaid
graph TD
    subgraph Data_Layer [Raw Data Layer]
        A1[yfinance: OHLCV daily]
        A2[FRED: macro rate_diff, yield_curve]
        A1 & A2 --> B[Data Integration]
    end

    subgraph Feature_Layer [Feature Layer]
        B --> C[base_features.py]
        B --> D[regime_features.py]
        B --> E[structural_features.py]
        B --> F[interaction_features.py]
        B --> G[macro features]
    end

    subgraph Model_Layer [Model Layer]
        C & D & E & F & G --> H[HybridRegimeEnsemble]
        H --> H1[Global backbone]
        H --> H2[Regime experts]
        H --> H3[Macro expert]
    end

    subgraph Regime_Layer [Regime Layer]
        D --> I[RegimeClassifier]
        I --> I1[KER + ADX + vol]
        I1 --> I2{TREND/RANGE/VOLATILE/NEUTRAL}
    end

    subgraph Signal_Layer [Signal Layer]
        H --> J[RegimeAwareSignalGen]
        I2 --> J
        J --> J1[Threshold 0.45]
        J --> J2[Confidence = max P]
    end

    subgraph Monitoring_Layer [Monitoring Layer]
        J1 & J2 --> K[Validity State Machine]
        K --> K1[GREEN 1.0 / YELLOW 0.5 / RED 0.0]
        K --> K2[Hysteresis + temporal smoothing]
    end

    subgraph Execution_Layer [Paper Trading Engine]
        K1 --> L[AssetEngine x6]
        L --> L1[BTC, GC=F, EURAUD, NZDJPY, CADJPY, USDCAD]
        L1 --> L2[Live inference every 30 min]
        L2 --> L3[Vol-scaled sizing + SL/TP]
        L3 --> L4[PnL tracking: state.json]
    end

    subgraph UI_Layer [Web Dashboard]
        L4 --> M[Flask/SocketIO Dashboard]
        M --> M1[Portfolio summary]
        M --> M2[Per-asset signal cards]
        M --> M3[Live execution log]
        M --> M4[Validity & regime monitors]
    end
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
- Manages 6 AssetEngine instances (BTC, GC=F, EURAUD, NZDJPY, CADJPY, USDCAD)
- Two label architectures: tb20 (triple-barrier) and fwd60 (60-day forward return)
- Collects per-asset state into portfolio view
- Runs every 300s (configurable via `QUANTFORGE_REFRESH_INTERVAL` env var)
- Exposes state via JSON for dashboard

**REST API** (`paper_trading/serve.py`)
- Zero-dependency stdlib `http.server`-based REST API
- In-memory TTL cache per endpoint (5-30s), gzip compression for large responses
- `/ping` health endpoint, paginated `/trades.json?limit=N&offset=M`
- Auto-refresh every 30 seconds (frontend react-query `refetchInterval`)

**Dashboard** (`paper_trading/dashboard/` — React + Vite + Tailwind + react-query)
- Full dark/light theme with localStorage persistence
- TradeFeed with pagination (prev/next), SignalsTable with asset name search
- Lazy-loaded FeatureCards on landing page (separate chunk, never loaded in main dashboard)
- Live/Delayed/Disconnected status badge with refetch spinner

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

```mermaid
graph TD
    R1[OHLCV daily] --> R2[weekly_pipeline.py]
    R3[Macro FRED] --> R2
    R2 --> R4[Feature engineering]
    R4 --> R5[Labeling]
    R5 --> R6[Walk-forward validation]
    R6 --> R7[Bootstrap gate]
    R7 --> R8[Model serialization]
    R8 --> R9[Paper trading ready]
```

### Paper Trading Pipeline

```mermaid
graph TD
    T1[yfinance 30 min] --> T2[Feature computation live]
    T3[Load model pickle] --> T4[Inference XGBoost]
    T2 & T4 --> T5[Signal + Confidence > 0.45?]
    T5 --> T6[Validity state machine check]
    T6 --> T7[Position management entry/SL/TP]
    T7 --> T8[Update state.json]
    T8 --> T9[Dashboard]
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
