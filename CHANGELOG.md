# Changelog

## v4.1.0 (2026-07-05)

### Documentation overhaul (Phases A+B)
- Wire `doc_drift_check.py` into CI pipeline
- Fix SELL_ONLY count references across 3 docs (8→3)
- Remove dead-code and non-existent script references from SYSTEM_OVERVIEW
- Create `CONTRIBUTING.md` with code standards and PR workflow
- Create `MONITORING.md` documenting all 11 Prometheus engine metrics
- Document shadow analytics engine (`paper_trading/shadow/README.md`)
- Document chaos testing framework (`tests/chaos/README.md`)
- Add module-level docstrings to 5 feature modules
- Update feature count in SYSTEM_OVERVIEW (19-35→21)
- Add `__init__.py` to `paper_trading/shadow/`

### Frontend audit remediation
- SystemBundleSchema + Zod validation for all 4 query hooks
- Slice selector migration for EmergencyHaltBanner, AssetCard, TickerRail
- Memoization improvements (arrow callbacks, selector narrowing)
- Modal component extraction (SystemHealthModal, WeeklyReview, TradeInspector)
- EquityHistoryChart deduplication
- Dead component cleanup (5 files removed)
- 23 frontend-audit commits merged

## v4.0.0 (2026-07-04)

### Portfolio expansion
- BTCUSD promoted with `weekend_eligible: true`, crypto [0,24] session tier
- 4 JPY crosses added (AUDJPY, NZDJPY, GBPJPY, USDJPY)
- 22 assets in production portfolio

### Codebase remediation (12 phases)
- Security: replace asserts with proper error handling, .env permission check
- YAML schema validator (`tools/check_config_schema.py`)
- Property-based sizing chain tests (Hypothesis framework)
- WAL concurrency stress tests (200-event multi-threaded)
- MT5 bridge security (loopback enforcement)
- MT5 bridge supervision (BridgeSupervisor + systemd unit)
- Structured JSON logging
- Prometheus metrics (zero-dep exposition)
- Pre-commit hooks (ruff, schema, firewall, assert guard, secret scanner)
- Chaos engineering framework
- ATLAS covariate shift detector (CUSUM + Page-Hinkley + KS)
- 1912 tests passing

## v3.0.0 (2026-07-02)

### Project rename: Quorrin → EigenCapital
- Python package git mv (179 files)
- Prometheus metric namespace `quorrin_*` → `eigencapital_*`
- Env vars `QUORRIN_*` → `EIGENCAPITAL_*`
- Dashboard branding, infra, remote updated
- AGENTS.md and README.md updated

### Production audit (15 phases)
- Trade lifecycle analysis (4679 reconstructed trades)
- Adaptive exit engine with retracement trailing
- Robustness gatekeeper (5-test suite)
- Shock simulation (7 classes, 21 scenarios, 0 catastrophic)
- MFE stationarity validation

## v2.0.0 (2026-06-30)

### TP/SL optimizer
- Grid search ratio space [0.5, 20.0] for all 21 assets
- Ratio=3.0 conservative cap (SL ≥0.71%)
- 11 assets bumped to ratio=3.0
- 8 optimizer tools built
- SL fragility test: 20/21 OK, 1 FRAGILE at 0.22%

### P3 factor model + P4 HRP
- Ledoit-Wolf shrinkage covariance estimator
- EWMA covariance (RiskMetrics decay)
- HRP fix (NaN handling, condensed distance)
- Factor constraints V2 (hard linear inequalities)
- `factor_constrained_v2` deployed as active weight strategy

## v1.5.0 (2026-06-26)

### Trend-exhaustion features (Tier 1+2)
- 6 new features: MACD hist, Stoch K/D, BB %B, ADX slope, RSI divergence
- SELL_ONLY reduced from 10→3 assets
- Walk-forward: total_R +33.2%, sharpe +12.8%, max_dd -55.4%
- 7 assets removed from SELL_ONLY
- 4 orphaned models moved to `models/orphaned/`

## v1.4.0 (2026-06-25)

### Live Sharpe tracker
- Cycle-level Sharpe with Lo autocorrelation adjustment
- Rolling daily Sharpe (7d, 30d, all-time)
- Slippage estimate from trace.jsonl

### USDCAD tp/sl swap
- tp_mult 2.03→2.5, sl_mult 2.5→2.03
- Ratio 0.81→1.23, estimated ΔR +139.1

### Monte Carlo drawdown V2
- R-multiple→% portfolio return conversion
- 10k sims: VaR(95) DD ≈ -2.3% at 1y
- 6 tp/sl optimizations applied

## v1.3.0 (2026-06-22)

### Portfolio remediation
- Signal encoding fix (SELL=0→1)
- MT5 realized_pnl fix
- Prometheus gate-blocked counter fix
- GBPUSD added to ASSETS dict
- 5 worst assets removed (DJI, ES, NQ, GBPJPY, USDJPY)
- 16-asset portfolio: total_R +175.79, Sharpe 13.70
- Adaptive Exit Engine (breakeven lock + retracement trail + time decay)
- MFE stationarity confirmed (KS p=0.186)

## v1.2.0 (2026-06-20)

### Walk-forward methodology correction
- CRIT-1 purging added (86% leakage fixed)
- Corrected metrics: total_R=107.82, sharpe_adj=9.66
- Ensemble disabled (ADR-026, p=0.1685)
- 19 assets, 171 OOS days

### BUY inversion discovery (Phase 2)
- 11 assets identified with inverted BUY signals
- SHAP audit: two mechanisms (dxy_mom_21d, carry_vol_adj)
- Counterfactual ablation: both falsified as causal
- SELL_ONLY filter deployed (9 assets initially)
- Directional asymmetry confirmed structural

### Causal replay chain
- WAL events: features_snapshot, inference_output, decision_output
- feature_hash + model_hash threading
- 21 replay-determinism tests

## v1.1.0 (2026-06-19)

### Carry fix + regime model fix
- Carry feature always zero bug fixed (rate_diff column name)
- Regime model at inference: load guard + missing features both fixed
- Hurst constant bug fixed (raw=True)
- 22/22 assets show varying regime probabilities

### Pipeline fixes
- Indentation nesting fix (_detect_bar_jump at module level)
- Spread gate (per-asset-class threshold, 720-cycle observe mode)
- Bar-jump suppression (60min on data-source switch)
- Risk-off suppression (AUDUSD flat when VIX>0 & SPX<0)

## v1.0.0 (2026-06-17)

### First stable release
- 22-asset portfolio paper trading live
- Per-asset XGBoost base models
- 15-layer governance framework
- PEK (Portfolio Execution Kernel) admission control
- EngineOrchestrator with 5-phase cycle
- MT5 bridge execution (Exness demo)
- Dashboard React SPA
- SQLite WAL persistence with replay
- Walk-forward validation pipeline
- Triple-barrier labeling
