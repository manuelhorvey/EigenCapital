# Production System Spec v1.0

**EigenCapital** — Cross-Sectional Factor Ranking & Paper Trading System

*Final clean architecture document. Defines what the system IS, not what it evolved from.*

---

## 1. System Identity

EigenCapital is a **factor-based asset allocation system** with a **walk-forward validated screening pipeline**, **per-asset binary XGBoost models**, a **5-layer portfolio maturity framework (P0–P4)**, and a **paper trading execution layer**.

It is NOT a directional prediction system. It does NOT attempt to forecast price movements. It ranks assets on weak but positive IC signals and constructs a long/short equity-style basket.

### What the system produces

1. **Screening output**: Composite scores + promotion classifications (GREEN/YELLOW/RED) for 30+ tickers
2. **Per-asset models**: Binary XGBoost classifiers, one per promoted asset
3. **Live signals**: BUY/SELL/FLAT decisions every 60s for 16 assets (SELL_ONLY filter overrides BUY→FLAT for 3 assets)
4. **Portfolio allocation**: Config-gated portfolio weight strategy (P0, active: factor_constrained_v2) with governance overlay
5. **Execution traces**: Full attribution records (prediction, execution, exit, friction) per trade

### What the system does NOT do

- Does NOT predict price direction with consistent accuracy across all assets
- Does NOT use ensemble/regime routing — disabled portfolio-wide (base_weight=1.0); see ADR-026
- Does NOT use FRED macro data in the live pipeline
- Does NOT operate with live capital (paper trading only)
- Does NOT deploy every screened ticker (approximately 13 of 36+ screened RED, not promoted)

---

## 2. Architecture Overview

The engine runs a continuous 5-phase orchestrator cycle (PRE → 1a → 1b → 2 → 3 → 4). Each tick (every 60s) executes the following loop:

```mermaid
flowchart TD
    Start((Start Cycle)) --> PRE[PRE: PortfolioStateSnapshot\nRiskBudget + PerformanceState]
    PRE --> P1[Phase 1: REFRESH\nParallel actor refresh + signal gen\nThreadPoolExecutor 8 workers]
    P1 --> P2[Phase 2: VALIDITY\nParallel validity state updates]
    P2 --> P3[Phase 3: PORTFOLIO HEALTH]
    P3 --> CB{Circuit Breaker\n7-consecutive-loss / -15% DD?}
    CB -- tripped --> Halt[Flatten positions\nEmergency halt\nRecoveryScheduler backoff]
    CB -- passed --> FX[Factor Exposures\n9 factor groups]
    FX --> VAR[VaR / CVaR\nRolling 60-period]
    VAR --> MT5[MT5 Orphan Recon]
    MT5 --> MT5A[Phase A: Drain cleanup queues]
    MT5A --> MT5B[Phase B: Stale ticket detection]
    MT5B --> MT5C[Phase C: Dry-run orphan report]
    MT5C --> MT5D[Phase D: Self-healing adoption]
    MT5D --> CONC[Position Concentration\nNet-short skew threshold]
    CONC --> P4[Phase 4: PERSIST\nFlush buffers → SQLite WAL\nState snapshot → state.json]
    P4 --> Start
```

**Research & Training Pipeline** (offline, runs before deployment):

```
36+ tickers ──▶ walk_forward_backtest.py ──▶ score_tickers.py
                   3y window, 1y step        composite score
                   5 folds, per-asset pt_sl    IC + hit rate + bidir
                                              GREEN/YELLOW/RED
                                              ──▶ promotion_report.json

yfinance ──▶ fetch_asset_data ──▶ alpha_features ──▶ triple_barrier
  10y                           ~30 feature cols      label (pt_sl)
                                                       binary reduce
                                                       ──▶ XGBoost
                                                       binary:logistic
                                                       300 trees, d=2
                                                       ──▶ .json model
```

---

## 3. Screening Layer

### 3.1 Walk-Forward Backtest

**Entry point**: `python scripts/backtest/walk_forward_backtest.py --tickers T1,T2,T3,...`

| Parameter | Value |
|---|---|
| Train window | 3 years |
| Step | 1 year |
| Folds | 5 (expanding) |
| Label | triple barrier with per-asset pt_sl |
| Feature window | 10 years from yfinance |
| Per-asset pt_sl | BTC-USD: (2.5, 3.0); others: (1.5, 2.0) |

**Output** (per ticker in `walkforward/`):
- Fold IC JSON (`{ticker}_fold_ic.json`)
- Signal parquet (`{ticker}_wf_signals.parquet`)
- Summary CSV (`{ticker}_wf_summary.csv`)

### 3.2 Scoring & Promotion

**Entry point**: `python scripts/research/score_tickers.py`

**Composite score formula**:
- IC normalized (weight: 30%)
- Hit rate normalized (weight: 25%)
- Bidirectionality (long rate + short rate, weight: 25%)
- Fold consistency (positive fold ratio, weight: 20%)

**Classification criteria**:
| Class | Requirements |
|---|---|
| **GREEN** (promote) | Score ≥ 65, IC > 0.03, hit rate > 0.40, FLAT < 70%, ≥50% positive folds, long & short > 5% |
| **YELLOW** (watch) | Score ≥ 35 or meets all criteria except one |
| **RED** (skip) | Below YELLOW thresholds |

**Output**: `walkforward/promotion_report.json`, `walkforward/PROMOTION_REPORT.md`, `walkforward/ticker_map.json`

---

## 4. Training Layer

### 4.1 Data Ingestion

All data sourced from yfinance (no FRED in production):

| Function | Returns | Period |
|---|---|---|
| `fetch_asset_data(name, ticker)` | (prices, rate_diffs, dxy, vix, spx, commodities) | 10y |
| `fetch_asset_ohlcv(ticker)` | DataFrame(open, high, low, close, volume) | 10y |

Rate_diffs are simulated from TNX yield with noise. All indices normalized to TZ-naive `datetime64[ns]`.

### 4.2 Feature Engineering

**Alpha features** (`features/alpha_features.py:build_alpha_features()`):

| Feature | Formula |
|---|---|
| `{ASSET}_carry_vol_adj` | Close return normalized by rolling vol |
| `{ASSET}_mom_21d` | `close.pct_change(21)` |
| `{ASSET}_mom_63d` | `close.pct_change(63)` |
| `{ASSET}_mom_126d` | `close.pct_change(126)` |
| `{ASSET}_mom_252d` | `close.pct_change(252)` |
| `{ASSET}_zscore_20` | `(close - SMA20) / std(close, 20)` |
| `{ASSET}_vol_ratio` | Short-term vol / long-term vol |
| `{ASSET}_dow_signal` | Day-of-week encoding |
| `dxy_mom_21d` | DXY 21-day return |
| `vix_mom_5d` | VIX 5-day return |
| `spx_mom_5d` | SPX 5-day return |
| `WTI_mom_21d` | WTI 21-day return |

13 feature columns per asset. Some assets have additional `yield_slope` or `mom126` variants.

### 4.3 Labeling

**Function**: `features/labels.py:triple_barrier_labels()`

1. Compute ATR-based barrier distances from `pt_sl = (tp_mult, sl_mult)`
2. Triple-barrier touch → {-1 (SELL), 0 (HOLD), 1 (BUY)}
3. Binary reduction: drop HOLD (0), map {-1, 1} → {0, 1}

**Default pt_sl**: per-asset from `configs/paper_trading.yaml`.

### 4.4 Model Training

**Algorithm**: XGBoost `binary:logistic`
**Architecture**: Single binary XGBoost per asset (ensemble + regime model disabled portfolio-wide; see ADR-026)
**Hyperparameters**:

| Parameter | Value |
|---|---|
| n_estimators | 300 |
| max_depth | per-asset (2–5, from `configs/paper_trading.yaml`) |
| learning_rate | 0.02 |
| objective | `binary:logistic` |
| random_state | 42 |
| n_jobs | 1 |
| tree_method | `hist` |

**Training window**: Last 5 years of data (minimum 200 rows)
**Train/val split**: 80/20 chronological, stratified if min class count ≥ 2
**Serialization**: `model.save_model(path)` → `.json` format
**Post-training**:
- PSI baseline persist
- Meta-label model (XGBoost)
- Regime-conditional model (trained via `scripts/training/train_regime_models.py`, not loaded in production — ensemble disabled)
- Feature importance + stability logging

### 4.5 Model Files

Location: `paper_trading/models/{asset_name}_model.json`
Format: XGBoost `.json` (not pickle)

---

## 5. Inference Layer

### 5.1 Pipeline (`paper_trading/inference/pipeline.py`)

**Frequency**: Every 60 seconds (configurable via `EIGENCAPITAL_REFRESH_INTERVAL`; default 60)

**Parallel execution**: 16 AssetEngine instances run via ThreadPoolExecutor (max_workers=8) in phases: REFRESH+Signal (parallel), VALIDITY (sequential), PORTFOLIO health, PERSIST.

**Steps**:
1. `fetch_live(ticker)` — 5y OHLCV (`_FETCH_PERIOD = "5y"`)
2. Normalize index to UTC TZ-naive date (fixes FX cross date shift)
3. `refresh_price()` — real-time price via MT5 bridge or 5d fallback
4. `ffill()` close column, deduplicate index
5. `fetch_asset_data()` + `build_alpha_features()` — alpha_df (13 feature cols)
6. Generate regime features from OHLCV (7 cols via `generate_regime_features`)
7. Archetype features from OHLCV: ema_spread, ADX(14), RSI(14), BB_zscore(20)
8. PSI drift check (rolling 21d vs baseline; skipped first cycle)
9. Inference truncation validation — if proven safe, predict only last row
10. XGBoost predict → 3-column proba expansion:
    ```python
    if raw.shape[1] == 2:  # binary model
        proba = np.column_stack([1.0 - raw[:,1], zeros, raw[:,1]])
    ```
11. **Calibrate probabilities** — apply per-asset BinnedCalibrator (P1; config-gated, enabled). ECE 0.36→0.02.
12. Ensemble blend skipped (disabled portfolio-wide; base_weight=1.0)
13. Meta-label inference (XGBoost, continuous size scalar)
14. `FixedThresholdStrategy(threshold=0.45)` → SignalType (BUY/SELL/FLAT)
15. Archetype classification → `TradeDecision(close_price, confidence, probs, ...)`
16. Refresh MT5 spread for spread gate
17. Decision pipeline (22 stages, `DEFAULT_STAGES`):
    a. First-cycle suppression — suppress trading on cold-start cycle 1
    b. Bar-jump suppression — suppress 60min if bar count changed >100
    c. Store prediction metadata — record pre-decision signal state
    d. Update MAE/MFE — update max adverse/favorable excursion
    e. Resolve signal — map proba to BUY/SELL/FLAT via FixedThresholdStrategy(0.45)
    f. Risk-off suppression — flat AUDUSD when VIX>0 & SPX<0
    g. VIX gate — suppress CL=F when VIX > 30; fail-open if VIX data missing or stale
    h. Sell-only filter — override BUY→FLAT for 3 inverted-BUY assets
    i. Spread gate — block entry if spread > per-class tier (observe 720 cycles)
    j. Session gate — block entry outside market session hours per asset-class tier (observe 720 cycles)
    k. ADX entry gate — block entry if ADX below threshold (observe-only, disabled by default)
    l. Confidence gate — abort if net confidence below threshold
    m. Signal hysteresis — 2-of-3 agreement before flip
    n. Meta-label advisory — record meta-label recommendation (no enforcement)
    o. Update regime bar counter — track bars since last regime shift
    p. Conviction gate — flip gate based on regime conviction
    q. Kelly sizing (P2) — scale position by Kelly criterion (config-gated, disabled)
    r. Manage position — close/re-open with entry gate check (includes embedded profit lock — blocks flip if unrealized PnL > threshold)
    s. Build entry artifacts — construct TradeDecision for execution
    t. Route execution policy — direct to PaperBroker or MT5Broker
    u. Poll deferred entries — execute pending deferred orders
    v. Update prob history — record probability history for drift monitoring
18. Governance (15 mechanisms + HealthMonitor + VaR/CVaR): validity, feature stability, meta-label, macro narrative, liquidity, PSI drift, sell-only filter, calibration (P1), Kelly sizing (P2), factor model (P3), equity cluster alarm, circuit breaker, portfolio drawdown, entry deviation, profit lock
19. Position sizing chain (P2 Kelly multiplier → drawdown taper → position cap → risk cap → leverage budget → backstop) + independent MT5 sizing
20. MT5 lifecycle: open → bridge `place_order` with SL/TP; close → bridge `close_position`; SL/TP adjust → bridge `modify_position`

### 5.2 Signal Contract

| Condition | Result |
|---|---|
| `prob_long > 0.45` AND `prob_short <= 0.45` | BUY |
| `prob_short > 0.45` AND `prob_long <= 0.45` | SELL |
| Both > 0.45 | BUY (long wins by order) |
| Neither > 0.45 | FLAT |

### 5.3 Archetype Classification

Computed from OHLCV feature vector (no model inference):

| Archetype | Triggers |
|---|---|
| MOMENTUM_IGNITION | Rate-of-change acceleration + EMA structure |
| MEAN_REVERSION | Overextended BB + RSI extremes |
| BREAKOUT_TEST | KER + ADX + vol contraction |
| VOL_EXPANSION | Vol z-score spike + compression release |
| UNKNOWN | Default fallback |

---

## 6. Portfolio Layer

### 6.1 Current Composition

**16 assets** promoted from 36-ticker walk-forward screening, P0 factor_constrained_v2 weighted.

**Added 2026-06-22:** GBPUSD promoted (walk-forward IC 0.186, HR 0.371, pt_sl=(1.97, 0.52) → R:R=3.79).

**Added 2026-06-26:** USDJPY, GBPJPY re-promoted after Step 3 trend-exhaustion features improved BuyWR above breakeven WR.

**Removed 2026-06-20:** AUDNZD, EURUSD, AUDCHF, GBPNZD (directional instability). USDCAD/NZDUSD halved 5%→2.5%.

**2026-06-30:** 11 assets bumped to ratio=3.0 via geometric mean constraint. See AGENTS.md for full chronology.

**SELL_ONLY filter active for 3 assets** (BUY→FLAT): CADCHF, NZDCHF, EURAUD.

| Asset | Ticker | Allocation | sl_mult | tp_mult | max_depth |
|---|---|---|---|---|---|---|---|---|---|---|
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

### 6.2 Position Sizing

**Strategy**: Config-gated via `portfolio.weight_method` (active: `factor_constrained_v2`).
**8 registered strategies**: `equal_v1`, `risk_parity_v1`, `risk_parity_v2`, `risk_parity_v3`, `hrp_v1`, `factor_constrained_v1`, `factor_constrained_v2`, `conviction_weighted_v1`.
**Computation**: `shared/portfolio_weights.py:compute_weights()` — PURE function (same returns → same weights).
**Covariance**: Raw historical returns only (no governance scaling).

**Size scalar chain**:
```
final_size = base × kelly_multiplier × governance_scalar × meta_confidence_scalar
→ cap by max_position_pct_of_equity
→ cap by risk_per_trade_pct
→ atomic decrement from leverage budget
```

**Kelly multiplier (P2, disabled by default)**: `compute_kelly_multiplier(calibrated_prob, tp_mult, sl_mult)`.
**Drawdown taper**: Linear between start_dd/end_dd.
**Backstop Phase 3**: Ratchets down on leverage budget breach, decays 0.9/cycle otherwise.

### 6.3 Governance Layers (15 + HealthMonitor)

| Layer | Frequency | Effect |
|---|---|---|
| Validity state machine | Per tick | Exposure 0–100% |
| Feature stability | Per retrain | Validity penalty |
| Meta-labeling (XGBoost) | Per signal | Size scalar [0–1] |
| Macro narrative | Weekly | SL +10%, size −20% |
| Liquidity regime | Per signal | SL +15/30%, size −15/30%, halt |
| PSI drift | Per cycle | Validity penalty, halt at 3+ SEVERE |
| Sell-only filter | Per decision | Override BUY→FLAT for 3 inverted-BUY assets |
| Calibration (P1) | Per inference | Remap raw p_long via BinnedCalibrator; config-gated, enabled |
| Kelly sizing (P2) | Per decision | Scale position by Kelly criterion; config-gated, disabled |
| Factor model (P3) | Per cycle | Factor exposure monitoring in state.json; 9 groups |
| Equity cluster alarm | Per cycle | Flags ES/NQ/^DJI all same side (recommendation, 60s throttle) |
| Circuit breaker | Per cycle | Multi-condition: dd, vol spike, halt ratio, consecutive losses (threshold=7) |
| Portfolio drawdown | Per cycle | Circuit breaker at −15% |
| Entry price deviation gate | Per entry | Skip if price drifted >2% |
| Sell tripwire | Per exit | SELL-only 20-trade window, 65% WARNING threshold |
| Profit lock gate | Per flip (embedded in manage_position) | Block flip if PnL >15% |

**HealthMonitor** runs in Phase 3g: portfolio vol, VaR(95), CVaR, halt ratio, equity cluster alarm, circuit breaker checks.
**RecoveryScheduler** probes halted actors with exponential backoff in Phase 3g.
**Live VaR/CVaR**: Rolling 60-period portfolio returns → VaR(95)=5th percentile, CVaR=mean of tail.
**Schema migration**: SQLite at `DB_SCHEMA_VERSION = "2.0.0"`. Auto-migrates at connect time — adds `cycle_id` to trades, `vol_spike`/`var_95` to equity_history, and indexes.

Plus decision pipeline stages (22 stages: first-cycle, bar-jump, store metadata, update MAE/MFE, resolve signal, risk-off, sell-only filter, spread gate, session gate, ADX entry gate, confidence gate, hysteresis, meta-label advisory, regime bar counter, conviction gate, kelly sizing, manage position [includes profit lock], build artifacts, route execution, poll deferred, update prob history) and position sizing guardrails (drawdown taper, per-position cap, risk-per-trade cap, leverage budget, backstop multiplier).

---

## 7. Data Contract

### 7.1 Sources
| Source | Data | Notes |
|---|---|---|
| MT5 (primary) / yfinance (fallback) | Daily OHLCV for all assets | MT5 bridge with yfinance fallback |
| yfinance | DXY (DX-Y.NYB), VIX (^VIX), SPX (^GSPC), WTI (CL=F), TNX (^TNX) | Macro data |
| FRED | Not used in production | Historical research only |

### 7.2 Index Convention

All date indices are `datetime64[ns]` at daily resolution, TZ-naive.
The pipeline normalizes `fetch_live()` output:
```python
df.index = pd.to_datetime(df.index.tz_convert("UTC").date)
```

### 7.3 Calibration Models

Calibration models stored at `paper_trading/models/calibration/{asset}.json`

### 7.4 Caching

In-memory TTL cache per download type:
- OHLCV: 60s TTL
- Realtime price: 5s TTL
- Macro data (DXY, VIX, SPX, WTI, TNX): 300s TTL, batched into single `yf.download` call

---

## 8. System Invariants

1. **No train/serve skew**: Same alpha feature builder in training and inference
2. **TZ-naive date alignment**: All pipeline stages use UTC dates
3. **Per-asset model independence**: Separate binary XGBoost per asset
4. **Walk-forward validated**: Every promoted asset passes expanding window backtest
5. **Binary signal only**: HOLD dropped; model trains on {-1, 1}
6. **Single entry authority**: All entries through `_can_enter()`
7. **Frozen execution contract**: PolicyDecision → FillResult → AttributionRecord immutable chain
8. **Worst-wins governance**: Most negative penalty applied, not averaged
9. **Per-asset pt_sl**: Barrier geometry from config, applied label-time and runtime
10. **.json serialization**: No pickle in production
11. **Inference truncation symmetry**: Training uses 5y data; live inference fetches 5y, truncates to `_MAX_INDICATOR_LOOKBACK + 50` when validated
12. **SQLite state store**: All persistent state in single WAL-mode database; legacy JSON/parquet files are read-only fallbacks
13. **Parallel asset isolation**: 21 AssetEngine instances execute independently via ThreadPoolExecutor; health monitor tracks per-asset DEGRADED/HALTED states independently
14. **MT5 order lifecycle symmetry**: Every paper open → MT5 `place_order`; paper close → MT5 `close_position`; SL/TP adjust → MT5 `modify_position`
15. **HealthMonitor in Phase 3g**: VaR(95), CVaR, equity cluster alarm, circuit breaker check, RecoveryScheduler probe
16. **Schema migration**: DB_SCHEMA_VERSION = "2.0.0"; auto-migrates at connect time; idempotent
17. **Sell-only filter**: BUY→FLAT for 3 assets with inverted calibration; deferred BUY canceled in entry_service.py
18. **P0 weight computation is PURE** — same returns → same weights regardless of engine state
19. **Calibration (P1) and Kelly sizing (P2) are config-gated** — no behavior change until explicitly enabled

---

## 9. File Map

| Path | Role |
|---|---|
| `configs/paper_trading.yaml` | Production config (19 assets, params) |
| `features/alpha_features.py` | Alpha feature factory |
| `features/data_fetch.py` | YFinance data ingestion |
| `features/labels.py` | Triple-barrier labeling |
| `features/archetypes.py` | Archetype classifier |
| `features/regime_features.py` | Regime detection features |
| `paper_trading/engine.py` | Engine orchestrator |
| `paper_trading/asset_engine.py` | Per-asset lifecycle |
| `paper_trading/portfolio_builder.py` | Portfolio from config |
| `paper_trading/state_store.py` | SQLite state persistence (5 tables, WAL mode) |
| `paper_trading/inference/pipeline.py` | Live inference pipeline |
| `paper_trading/inference/training.py` | Binary XGBoost training |
| `paper_trading/inference/async_diagnostics.py` | Deferred diagnostics (daemon consumer queue) |
| `paper_trading/orchestrator/engine.py` | Parallel asset orchestration (ThreadPoolExecutor) |
| `paper_trading/orchestrator/actor.py` | Per-asset actor with health state |
| `paper_trading/orchestrator/health.py` | HealthMonitor, CircuitBreaker (max_consecutive_losses=7), RecoveryScheduler |
| `paper_trading/orchestrator/engine.py` | EngineOrchestrator (ThreadPoolExecutor, 5 phases PRE→1a→1b→2→3→4 + MT5 sub-phases A–D inside Phase 3, VaR/CVaR in Phase 3g) |
| `paper_trading/models/` | Trained models (.json) — 16 assets (9 archived in `orphaned/`) |
| `paper_trading/state_store.py` | SQLite state persistence + schema migration (DB_SCHEMA_VERSION=2.0.0) |
| `paper_trading/execution/decision_pipeline.py` | DEFAULT_STAGES (22 stages), SELL_ONLY_ASSETS frozenset |
| `shared/portfolio_weights.py` | P0 portfolio truth layer — 4 weight strategies |
| `shared/calibration/` | P1 calibration — BinnedCalibrator, CalibrationRegistry, ECETracker |
| `shared/kelly.py` | P2 fractional Kelly sizing |
| `shared/factor_model.py` | P3 factor model — 9 groups, constrained optimization |
| `portfolio/hrp_allocator.py` | P4 HRP fix — optimal_leaf_ordering |
| `scripts/training/train_calibration.py` | Train calibrators from walk-forward parquets |
| `scripts/replay/replay_rebalance.py` | Reconstruct historical portfolio weights |
| `paper_trading/services/entry_service.py` | Entry validation + deferred-entry sell-only bypass fix |
| `benchmarks/microbenchmark.py` | Isolated performance benchmark (`--state-dir`) |
| `scripts/backtest/walk_forward_backtest.py` | Multi-ticker screening |
| `scripts/research/score_tickers.py` | Promotion scoring |
| `scripts/research/generate_promotion_report.py` | Report + YAML generation |
| `scripts/backtest/backtest_pnl.py` | PnL backtest from OOS signal parquets (R-multiples, autocorrelation-adj Sharpe) |
| `scripts/backtest/crisis_replay.py` | Crisis replay against 4 historical windows |
| `scripts/backtest/monte_carlo_drawdown.py` | Block-bootstrap drawdown simulation |
| `scripts/training/retrain_counterfactual.py` | Feature ablation walk-forward test |
| `scripts/diagnostics/check_chf_correlation.py` | CHF cluster independence verification |
| `walkforward/` | Screening results + counterfactual ablations |
| `LIVE_CONTRACT.md` | Immutable system contract |

---

## 10. Known Constraints

1. **Paper trading only** — no live capital execution
2. **Yahoo Finance / MT5 dual source** — MT5 primary data source with yfinance fallback
3. **FX cross price NaN on first cycle** — incomplete daily bar; resolves after next cycle with full bar
4. **Ensemble disabled** — base_weight=1.0 portfolio-wide; see ADR-026 for decision record and re-enable criteria
5. **19/36 tickers promoted** — rest are RED; reflects weak IC for most FX pairs
6. **No FRED** — macro derived from yfinance tickers only; no FRED API dependency in production
7. **JPY/CHF cross TZ issue** — fixed via UTC normalization + index deduplication in pipeline
8. **MT5 bridge 5s timeout** — MT5 `realtime_mid_price()` has a 5s socket timeout; during volatile periods, prices may lag
9. **Benchmark isolation** — `microbenchmark.py --state-dir` uses temp directory by default; must never point at production `data/live/`
10. **BUY inversion root cause unknown** — SELL_ONLY filter is empirically correct (76% of profit, outperforms in 3/4 crisis windows) but the underlying cause of inverted BUY calibration is unidentified. Two leading hypotheses (carry, DXY) were falsified by walk-forward ablation.
11. **Circuit breaker threshold=7** — lowered from 15 after crisis replay showed max 4 consecutive losses. Provides realistic safety margin while being reachable during severe drawdowns.
12. **Spread gate observe mode** — first 720 cycles (~6h) log what would be blocked without acting; enforcement activates automatically after observation window.
13. **P0 (factor_constrained_v2) and P1 (calibration) are enabled**; P2 (Kelly) is disabled pending 2+ weeks live data
14. **Calibration reduces ECE by 94.3%** but requires walk-forward parquet regeneration for retraining

---

*Spec version 1.1 — June 2026*
*Supersedes all prior documentation. Production code is truth.*
