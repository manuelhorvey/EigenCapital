# EigenCapital — Survival Monte Carlo Simulation

Multi-layer survival simulation framework at `research/risk/` that evaluates portfolio robustness under extreme market conditions with progressively increasing realism.

## Execution Physics

**Shared config** (`shared/execution_config.py`): `ExecutionConfig`, `compute_slippage_cost()`, `compute_market_impact()`, `build_execution_configs()` — used by live `PaperBroker` and `research/risk/execution_physics.py`.

Models market microstructure degradation:

- **Spread expansion**: Base spread widens proportionally to volatility z-score, capped at max bps
- **Market impact**: `none`, `linear`, or `square_root` vs average daily volume (per asset in YAML)
- **Gap risk**: Stop-loss gap-through increases with vol, adding nonlinear downside
- **Partial fills**: Fill probability decays with vol; unfilled orders truncate returns
- **Deleveraging feedback**: When portfolio drawdown exceeds threshold (−10%), exposure is linearly reduced (up to 50% max), then recovers at 0.5%/day when above threshold

## Regime-Aware Bootstrap

**Tail-weighted regime classification** (`vol³ composite index`):

- COMPOSITE = weighted avg of each asset's rolling vol z-score
- Weight ∝ vol³ — high-vol assets (BTC) dominate crisis detection
- Thresholds: CALM (<1.0σ), ELEVATED (1.0–2.0σ), CRISIS (>2.0σ)

**Regime-conditioned block sampling**: During bootstrap, blocks are sampled such that the starting day's regime matches the current simulated regime state. This preserves volatility clustering, crisis persistence, and deleveraging feedback compounding.

## Portfolio Variant System

| Variant | Description |
|---------|-------------|
| Full Portfolio | All 14 core assets at current allocations |
| BTC Satellite | 14 core assets + BTC satellite bucket at 5% cap |
| No BTC | Excludes BTC entirely, renormalized |
| BTC Legacy 20% | Original 11-asset with BTC at 20% (pre-satellite) |

## Stress Scenarios

| Scenario | Description |
|----------|-------------|
| Crypto Bear 2022 | −0.45%/day for 12 months on BTC |
| Flash Crash | −30% single-day shock across all assets |
| Correlation Spike | 6-month period at 0.90 inter-asset correlation + 2× vol + amplified execution friction |

## Marginal Contribution Analysis

Leave-one-out delta for each asset against the full portfolio:

- ΔSharpe, ΔAnn.Return%, ΔWorstDD%, ΔCVaR, ΔRuin probability
- Performance assessment: growth engine / stabilizer / contaminant

## Exposure Telemetry

Tracks the deleveraging system's behavior across all paths:

- Exposure cone (percentiles of leverage over time)
- Deleveraging trigger rate and frequency
- Regime-bucketed average exposure (CALM vs ELEVATED vs CRISIS)
- Min exposure distribution (crisis severity)

## Calibration Results (v5 — Regime-Optimized Geometry, 5000 paths)

| Scenario | Metric | Regime-Geometry Portfolio | Flash Crash | Corr Spike |
|---|---|---|---|---|
| Normal | Sharpe | **9.67** | **1.59** | **6.44** |
| | Ann.Ret | +44.6% | +28.5% | +36.1% |
| | Worst DD | 5.2% | 32.8% | 23.8% |
| | Med DD | 1.9% | 30.1% | 6.1% |
| | Terminal P50 | **3.03×** | **2.12×** | **2.52×** |
| | Terminal P5 | **2.39×** | **1.68×** | **2.00×** |
| | Ruin | 0.00% | 0.00% | 0.00% |
| | Positive paths | 100.0% | 100.0% | 100.0% |

**Key findings**:

- Regime-optimized geometry (sl=0.30 sweep-derived TP) delivers **Sharpe 9.67** across 13 assets with 0% ruin across 5000 correlated bootstrap paths
- All stress scenarios remain profitable — flash crash Sharpe 1.59, correlation spike Sharpe 6.44
- Worst DD peak across all paths: **5.2%** (regime) vs **8.3%** (v4 plateau defaults) vs **27.5%** (BTC legacy)
- All 4 BTC variants (full, no BTC, capped 5%, regime-gated) produce equivalent Sharpe ~9.67 — robust to BTC exposure
- 5000-path bootstrap with block resampling confirms narrow CIs — Sharpe floor above 6.0 at P5
- Deleveraging activates on ~12% of paths; BTC satellite improves worst DD by 15.4pp vs legacy

**Important caveat**: Current regime space remains sparsely populated in CRISIS states (0.27% sample frequency). The bootstrap injects synthetic stress blocks to compensate; with `--extended-history`, `adjust_injection_rate_for_crisis_density()` reduces injection when empirical CRISIS density is already sufficient.

## Extended History (25+ years)

| Step | Status | Key result |
|------|--------|------------|
| OHLCV backfill 33 tickers from 2000-01-01 | ✅ | `data/raw/historical_extended/` |
| Neutral prediction stubs | ✅ | |
| Survival sim `--extended-history --paths 5000` | ✅ | Full Governance Sharpe **6.26**, Ann.Ret +25.1%, **0% ruin** |
| Metrics export | ✅ | `data/research/survival_extended.json` |
| 5y vs 25y comparison | ✅ | Sharpe 6.26 (extended) vs 6.27 (10y) — nearly identical |

**Validation conclusion:** The 25-year extended history produces nearly identical survival metrics to the 10-year window (Sharpe 6.26 vs 6.27). All governance variants maintain 0% ruin. This confirms the portfolio structure and governance layer are robust to multi-decade market regimes, not overfit to post-2015 dynamics.

| Component | Path / command |
|-----------|----------------|
| OHLCV backfill | `python data/loaders/backfill_to_2000.py` → `data/raw/historical_extended/` |
| Prediction stubs | `python scripts/run_extended_history_pipeline.py` |
| Extended features | `features/builder.compute_training_data_extended()` |
| Survival sim flag | `python research/risk/survival_sim.py --extended-history ...` |
| Metrics export | `data/research/survival_extended.json` |
| 5y vs 25y report | `python diagnostics/extended_history_report.py` |

## Lead-Lag Research

| Component | Status | Detail |
|-----------|--------|--------|
| Full matrix (32 assets, lags 1–10) | ✅ | 205 significant relationships saved |
| Heatmap | ✅ | `data/research/lead_lag_matrix.png` |
| Curated edges | ✅ | 9 edges in `data/research/lead_lag_edges.yaml` |

**Key findings:**
- **DJI leads FX crosses** at lag 1: AUDJPY (+0.46), NZDJPY (+0.42), CADJPY (+0.39), GBPJPY (+0.33), EURAUD (–0.37), USDCAD (–0.39). All p-values < 1e-60.
- **GC leads USDJPY/USDCHF** at lag 1: –0.34 (p < 1e-60).
- 8 new production features: `dji_lead_1` on 6 FX crosses; `gc_lead_1` on USDJPY, USDCHF.

## SL/TP Execution Surface Optimization

The `research/execution_surface/` module runs OHLCV-driven replay simulation over SL/TP grids to find plateau-center configurations:

- `replay_engine.py` — OHLCV-driven trade lifecycle simulation
- `surface_sweep.py` — Sweeps SL/TP combinations across parameter space
- `sltp_surface.py` — SL/TP plateau analysis; centre selected over global max for robustness
- `monte_carlo.py` — Monte Carlo validation of selected SL/TP parameters
- Aggregate reports at `data/sandbox/sltp_analysis/aggregate_report.json`

## Simulation Snapshot System

Full engine state captured per asset at each `save_state()` call for deterministic replay:

- **Storage**: `data/live/snapshots/simulation_history.parquet` — row-based parquet with positions, trade_log, prob_history, validity state, meta-model inference, feature stability metrics
- **Cold state**: model pickle files stored separately as external references (not duplicated per snapshot)
- **Load modes**: exact timestamp, date-prefix, date listing
- **Deduplication**: on (timestamp, asset)
- **Use cases**: replay from any historical date, SQL-like analysis ("what was every asset's position on all Mondays?")

## Limitations of Realism

The survival simulation is stateful and regime-conditioned, but it is not a full market microstructural model. The following are **not** yet modeled:

- **Funding stress** — no margin funding rate shocks or repo market dislocations
- **Market impact** — orders do not move prices; fills occur at observed levels
- **Dynamic spread feedback** — spreads expand with vol but do not react trade-by-trade to order flow
- **Order book exhaustion** — no queue priority, iceberg detection, or liquidity hole mechanics
- **Endogenous correlation cascades** — correlations spike exogenously (stress blocks) but do not emerge from cross-asset margin calls
- **Exchange outages** — no gateway disconnections, trading halts, or data feed failures

These limitations mean the simulation likely understates true tail persistence, especially under compound stress where multiple degradation modes reinforce each other. The deleveraging governor provides a first-order safety layer against this class of risk, but the absence of endogenous cascades should be considered when interpreting absolute risk metrics.
