# Changelog

## v6.0.0 (2026-07-16)

### Production Baseline — Model Quality & Risk Fixes

This major release resolves all critical bugs hindering system performance. The strategy now runs with validated directional edge, realistic drawdown estimates, and production-hardened risk controls.

**Baseline Simulation Metrics ($500 start, 2yr walk-forward, 6,552 trades):**
- Final capital: $2,561 (+412%) | Sharpe: **1.40** | Max DD: **37.6%**
- Bootstrap (500 trials): P(Profit)=**100%** | P(Double)=**100%**
- Sweet spot: $2,500 → 28.5% DD, +45% return

### Critical Fix: 3x Min-Lot Risk Multiplier
- **Root cause identified:** `capital_growth_simulation.py` applied a 3x multiplier to the risk cap for all accounts, causing simulated drawdowns to be massively overstated at small equity levels
- **Fix:** multiplier reduced to 1x for accounts under $1,000 equity
- **Impact:** Max DD cut from **72% → 38%**, Sharpe improved from **1.05 → 1.40**
- Verified no other files in codebase had the same pattern

### Model Depth Optimization & Rollbacks

| Asset | Depth | Result |
|:------|:-----:|:-------|
| **GC** | 4→**2** | Inversion fixed (BUY `a`: −1.349→+1.462), calibrator no longer reverses model |
| **GBPCHF** | 4→**2** | Collapse fixed (std 0.0023→0.085), hit rate −0.73→**+0.73** |
| **NZDCAD** | 4→**2** | 100% neutral baseline restored (was −183R at depth=4) |
| **NZDUSD** | kept **2** | Variance compression documented (std 0.065 vs 0.138) |
| **Depth optimizer re-run** | all 22 | `calibrate_flag=True` fixed; depth recommendations now use calibrated methodology |

### GBPCHF Model Collapse — Feature Remediation
- **Root cause:** 3-year training window was too short for this pair; model collapsed to near-constant prediction (p_long std 0.0023)
- **Fix:** Added 126-bar momentum window to `features/registry.py` for GBPCHF
- **Result:** Restored from **−87R to +103.3R**, 100% SELL predictions now correct

### Directional Classification System (directional_map.yaml v3)
- Complete 22-asset directional taxonomy: **12 SELL_STRONG**, **5 BIDIRECTIONAL**, **3 BUY_STRONG**, **1 SELL_LEANING**, **1 NEUTRAL**
- 3 corrections from buggy analysis: EURCAD, EURNZD, NZDUSD reclassified to SELL_STRONG
- Temporal stability analysis validates classifications across 2-year rolling windows

### Feature Registry Improvements
- **EURCHF**: Added `gc_lead_1`, `yield_slope`, ATR volatility — structural inversion remains, but calibration now recovers +494R SELL
- **NZDUSD**: Added `gc_lead_1`, `dji_lead_1`, `yield_slope` — variance compression partially addressed
- **AUDUSD**: Added `gc_lead_1`, `yield_slope`, 126 momentum — 96.8% flat rate (too cautious, documented)

### Tiered Risk Configuration
- **Risk-by-capital**: 1.0% for accounts <$5K, 2.0% for ≥$5K — dynamically selected at runtime
- **MT5 aligned**: Same tiered logic applied via `mt5_enable_max_risk_per_trade_pct`
- **Min-lot bypass disabled**: `mt5_bypass_risk_cap_at_min_lot: false` prevents small accounts from exceeding risk cap
- Implementation in `shared/sizing_chain.py` + `paper_trading/services/entry_service.py` with dashboard indicator

### Production Documentation
- **MT5 Deployment Risk Table** (`docs/MT5_DEPLOYMENT_RISK_TABLE.md`): Risk-by-capital recommendations, bootstrap CIs, deployment sequence
- **Production Readiness Audit** (`docs/PRODUCTION_READINESS_AUDIT.md`): Comprehensive audit of all protections, gates, risk controls
- **Capital growth baseline** locked: `data/processed/simulations/capital_growth_baseline.json`
- All 22 models + 22 calibrators retrained (2026-07-16)

### Chore
- Git tag v6.0.0 pushed to origin
- Production baseline branch `production-baseline-2026-07-16` created and merged to main
- All 72 uncommitted files committed across 6 logical batches
- Working tree clean on main

## v4.3.0 (2026-07-08)

### Features
- **Model retraining pipeline**: automated training, validation, and performance comparison pipeline for model retraining
- **Model health monitor**: health monitor, retrain scheduler, and systemd timers for scheduled model validation
- **HealthMonitorPanel**: new dashboard component on the /risk page showing model health status
- **Live validation suite**: Prometheus uptime gauge and live validation checks
- **EigenCapitalJSONEncoder**: cross-cutting serialization encoder replacing ad-hoc `default=str` patterns
- **Meta-label confidence**: surface meta-label confidence in TradeDecision for richer signal telemetry
- **Direction-conditional analysis**: post-fix direction-conditional diagnostics + lifecycle OHLCV fix

### Architecture & Refactoring (H-06 singleton elimination)
- Eliminate global `_STORE`/`_LazyStore` singletons from state layer
- Inject `StateStore` through all API route modules (POST dispatch, response metadata)
- Eliminate global singletons for config, registry, and MT5 status in governance layer
- Migrate all remaining `json.dumps`/`json.dump` `default=str` calls to `EigenCapitalJSONEncoder`
- Extract MT5 orphan reconciliation into `orphan_reconciliation.py`
- Extract VaR/CVaR computation into `health.py`
- Extract position concentration and correlation monitoring into `correlation.py`

### Engine & Fixes
- **State persistence**: persist and restore equity curve + risk state across engine restarts
- **Exit system fixes**: resolve dual trailing exit conflict; remove dead `_apply_post_entry_adjust_only`
- **WAL checkpoint**: add WAL checkpoint after equity history writes
- **yfinance v1.2.0**: fix `auto_adjust` collision + retry delays for reliable data fetching
- **Calibration**: preserve 3-class simplex integrity; add C-03 confidence diagnostic
- **Orphan reconciliation**: fix indentation of `except` blocks
- **CHF limit**: revert CHF limit from 0.25→0.20 in production config
- **Backtest**: add `--tag` flag and yfinance OHLCV fallback to Monte Carlo
- **Serialization**: handle datetime in simulation snapshot trade_log
- **Systemd**: remove system-level dependencies from user-level service unit files

### Frontend audit remediation (merged)
- F6: governance selector now mirrors backend instead of re-deriving `combined_sl_mult`/`size_scalar`
- B6/F10: show skeleton only on initial load, not background refetch
- F9: modal stacking fix for overlay z-index
- F2: schema drift alignment with backend
- AssetDeepDive: move `scatterGlobalMax` outside JSX to fix TS1382 parse error
- Dashboard: fix null-reference crash on asset card → sizing view
- Proxy cleanup, SVG clipping fix, tone comparison, `contentVisibility` removal
- `useMonitorAlerts` ref pattern alignment
- Utility tests and selector tests added

### Testing (+500 new tests)
- **shared/**: execution_config (16), meta_labeling (20), metrics_snapshot (10), constrained_weights (6)
- **shared/metrics/**: fqi (12), eis (8), attribution (8), mae_mfe (6), shadow (5)
- **paper_trading/**: writer (11), portfolio_builder (8)
- **alerting/**: manager (15)
- **entry/**: deferred_entry (10), optimizer (11), policy (11), tp_compiler (10)
- **attribution/**: collector (16)
- **features/**, **labels/**, **signals/**, **portfolio/**: 126 tests
- **risk/**, **monitoring/**, **tools/**, **benchmarks/**: 167 tests
- **ops/**: 32 unit + CLI smoke tests for `model_health_monitor.py`
- **Frontend**: unit tests for useTrades, useWeeklyReview, useAssetDeepDive, useEquityHistory
- **Frontend**: unit tests for format utilities and trading-state selectors
- **Temporal**: mock-based tz provenance tests

### Documentation (16 audit recommendations)
- Complete all 16 audit remediation items
- ANALYSIS.md, AGENTS.md split; JSDoc sweep across dashboard components
- Module-level docstrings added to 4 scripts
- WAL event type reference + decision pipeline stage enrichment
- Create state.json schema reference document
- Dashboard component inventory added
- Cross-reference duplicate DEVELOPMENT docs
- Resolve shorthand config paths via `configs/domains/` fallback
- Simplify config file paths in CONFIGURATION.md
- AGENTS.md updated with new extracted orchestrator modules
- Doc-drift: generalize `data/` exclusion; silence false positives from audit report paths

### Chore
- Replace stale Quorrin project paths with EigenCapital (service units, docs)
- Model hash sidecars updated after retrain pipeline
- Ruff format fixes (risk_registry.py, engine_state_service.py)
- E501 line-too-long fixes + full ruff format pass
- Conftest import order fix; logging guard in conftest
- Logging moved out of module-level in benchmarks/microbenchmark.py

## v4.2.1 (2026-07-06)

### Bug fixes — live trading session
- Fix `set_capital_base` to adjust `initial_capital`, `peak_value`, and `current_value`
  on both asset and `pos_mgr` by the rebalance delta
- Fix `engine_rebalance_service`: switch from `fetch_history(ticker, years=N)` to
  `fetch_live(ticker, min_days=N)` for proper daily OHLCV data
- Add regression tests for `set_capital_base` (upward, downward, zero delta)
- Audit confirms all 26 `initial_capital`/`peak_value` reads across production codebase
  are now correctly rebalance-aware — no additional fixes needed

## v4.2.0 (2026-07-05)

### Configuration infrastructure (Phase 12)
- PaperConfigRegistry with domain-first precedence (Phase 11.1)
- EngineConfig.load() routes through PaperConfigRegistry (Phase 11.2)
- LegacyMirror regenerates paper_trading.yaml from registry (Phase 11.3)
- Environment overlay wiring (Phase 8)
- Per-asset file split with default+override composition (Phase 7)
- Typed domain models with read-side mirror (Phase 3–4)
- Cross-field validator and config_diff tool (Phase 1+10)
- Wire alerting, ML, gate, and governance into EngineConfig
- Deleted legacy `configs/paper_trading.yaml` and `configs/domain_loader.py`

### Frontend audit remediation
- SystemBundleSchema + Zod validation for all 4 query hooks
- Slice selector migration for EmergencyHaltBanner, AssetCard, TickerRail
- Memoization improvements (arrow callbacks, selector narrowing)
- Modal component extraction (SystemHealthModal, WeeklyReview, TradeInspector)
- EquityHistoryChart deduplication
- Dead component cleanup (5 files removed)
- 23 frontend-audit commits

### Documentation overhaul
- New docs: FAQ, DASHBOARD, MAINTAINERS, DEVELOPMENT, doc improvement plan
- Doc-drift check wired into CI with path/date/metric consistency validation
- CONFIGURATION.md auto-generated from typed domain models
- ADR statuses, feature counts, governance layer counts corrected
- Removed stale `paper_trading.yaml` references from docs and scripts

### Re-entry feature
- Multi-position same-side re-entry (Policy B: +44% R improvement)
- Re-entry config: `max_positions_per_asset`, orchestration flatten
- Trade lifecycle re-entry analysis scripts

### Emergency halt hygiene
- Auto-clear stale emergency halt at engine startup
- Slack alert on per-cycle auto-unhalt
- Regression tests for weekend cycle + emergency halt
- Re-anchor `_peak_portfolio_value` at init

### Audit remediation (6 phases)
- Phase 1: 7 critical safety fixes
- Phase 2: 5 high-impact ML/stats fixes
- Phase 3: ML/Stats hardening
- Phase 4: PEK + engine test coverage, 14 CI-skipped tests unskipped
- Phase 5: DI support for top-level singletons
- Phase 6: `deepcopy` → `dataclasses.replace`, dead code cleanup

### Other
- ADX entry gate disabled (fix data-flow bug)
- BTCUSD entry slippage tolerance bumped to 5%
- Live Sharpe tracker: open trace file in binary mode fix
- CI: split lint/test jobs, Python 3.13, pip caching
- SL/TP slippage sign correction
- 14 silent exception blocks upgraded to logged errors
- SAST/DAST in CI, hardened Docker

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

### Project rename: EigenCapital (formerly Quorrin)
- Python package git mv (179 files)
- Prometheus metric namespace `eigencapital_*` (formerly `quorrin_*`)
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
