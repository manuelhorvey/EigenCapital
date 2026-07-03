# Changelog

All notable changes to EigenCapital are documented in this file. Releases are
pinned via git tags; this changelog is regenerable from git history.

The format is broadly [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)-inspired
but adapted to a research + paper-trading release cadence (irregular, dated by
session, not weekly). Updates follow the date-header convention used in
`AGENTS.md`.

---

## Unreleased

### Documentation
- **Audit & synchronize** (2026-06-30): Comprehensive review of all 64
  documentation files vs. implementation. Resolved 27 mismatches:
  - README.md: phase count 4 → 5 (PRE + 1a/1b/2/3/4); portfolio badge 19 → 21;
    pre-leak-fix baseline block marked superseded.
  - AGENTS.md Key Files table: 6 `risk/*` paths moved to `paper_trading/pek/*`.
  - AGENTS.md feature count taxonomy: "11 core" / "13 base" → "9 base"
    (canonical 9 + 6 trend-exhaustion + 4 cross-asset + COT).
  - De-duplicated "Small MT5 equity ($107 demo)" Known Issues bullet.
  - SYSTEM_OVERVIEW.md: `WALRunner` → `ReplayRunner` (2 places); added
    `strategy_metadata` to persistent tables list; de-duplicated `StateStore`.
  - LIVE_CONTRACT.md §6: feature-builder description normalised to canonical
    taxonomy (15 per-asset with OHLCV, 9 without; cross-asset + COT).
  - PRODUCTION_SYSTEM_SPEC_v1.md: phase count 3 → 5; model count 19 → 21.
  - ADR-027 source-code path references updated to `paper_trading/pek/`.
- Added this `CHANGELOG.md`.
- Added `docs/SECURITY.md` (auth, MT5 loopback, .env permission check).
- Added `docs/MODES.md` (per-mode override matrix derived from
  `configs/paper_trading.yaml`).
- Added `tools/doc_drift_check.py` (asset-count + key-file + phase-counter
  linters for CI enforcement).

---

## v2.0.0 — 2026-06-30 (Codebase Remediation Roll-up)

14 months of hardening rolled up (from `refactor/codebase-remediation` branch):
- **MT5 bridge**: loopback enforcement + supervisor with `/health` endpoint +
  systemd unit + 34 contract tests.
- **Observability**: JSON logging, Prometheus metrics registry, ATLAS layered
  change-point detector (CUSUM + Page-Hinkley + KS).
- **Security**: replace bare asserts, `.env` world-readable permission check,
  secrets scanner, import firewall, pre-commit hooks.
- **Testing**: property-based sizing invariants, WAL concurrency stress
  (200 events, 8 threads), circuit-breaker regression suite (33 tests).
- **Schema migration**: SQLite bumped to `DB_SCHEMA_VERSION = "2.0.0"`.

See `AGENTS.md` "Codebase Remediation (2026-06-30+)" for full list.

---

## v1.5.0 — 2026-06-29 (rename release)

- Project renamed `QuantForge` → `EigenCapital`.
- Author handle rotated `MktOwl` → `Eleven Forge`.
- `CLOSE_*` feature naming artifact resolved — features now use real asset
  ticker prefixes (no more `prices.to_frame("close")` collision).
- Charts, badges, README manifs updated.

---

## v1.4.0 — 2026-06-28 (TP/SL Optimizer Ratio=3.0 pass)

- 11 assets bumped to ratio=3.0 via `scripts/optimization/portfolio_sltp_optimizer.py`.
  See `AGENTS.md` "TP/SL Optimizer — Ratio=3.0 Bump (2026-06-30)" for
  per-asset table.
- All 16 models retrained with new labels.
- Dashboard `/optimization.json` endpoint added.
- SL fragility test (`scripts/optimization/sl_fragility_test.py`) confirmed
  20/21 OK, 0 CRITICAL, 1 FRAGILE (NZDCAD).

---

## v1.3.0 — 2026-06-26 (Trend-Exhaustion Features + SELL_ONLY Reduction)

- 6 new trend-exhaustion alpha features: MACD histogram, Stochastic %K/%D,
  Bollinger %B, ADX slope, RSI divergence. Computed when OHLCV is provided.
- Walk-forward total R +33.2%, sharpe_adj +12.8%, max_dd_R −55.4%.
- SELL_ONLY_ASSETS reduced from 10 → 5 (removed GBPJPY, USDCHF, EURCHF,
  USDJPY, ^DJI).
- 4 models moved to `paper_trading/models/orphaned/`: EURUSD, AUDNZD, AUDCHF,
  GBPNZD.

---

## v1.2.0 — 2026-06-25 (Factor Constraints + Covariance Estimators)

- `factor_constrained_v2` adopted as `weight_method` (best risk-return tradeoff).
- Ledoit-Wolf shrinkage (`risk_parity_v2`) and EWMA span-60 (`risk_parity_v3`)
  covariance estimators added.
- HRP `scipy.cluster.hierarchy` issues fixed: zero-variance drop + condensed
  distance matrix via `scipy.spatial.distance.squareform`.
- USDCAD tp/sl swapped (2.03/2.5 → 2.5/2.03) for ratio 1.23.

---

## v1.1.0 — 2026-06-25 (Live Sharpe Tracker + Monte Carlo V2)

- `paper_trading/performance/live_sharpe.py` — `LiveSharpeTracker` records
  portfolio sharpe in `state.json:portfolio.live_sharpe`.
- `scripts/backtest/monte_carlo_drawdown.py` V2 — converts R-multiples to
  % portfolio return via per-asset ATR_pct.

---

## v1.0.0 — 2026-06-23 (Production-Stable Release)

- BUY Inversion Discovery closed; SELL_ONLY filter frozen at 8 assets after
  Counterfactual Ablation.
- Replay-First Architecture: `features_snapshot`, `inference_output`,
  `decision_output` WAL events.
- MT5 Orphan detection/adoption (Phase A–D).
- Position concentration WAL alert.
- Maestro 33 circuit-breaker regression tests across 4 test files.

---

## v0.5.0 — 2026-06-20 (Walk-Forward PnL Backtest)

- Ensemble disabled portfolio-wide (ADR-026, base_weight=1.0).
- AUDNZD, EURUSD, AUDCHF, GBPNZD removed from trading.
- USDCAD/NZDUSD allocations halved (5% → 2.5%).
- Walk-Forward PnL backtest (`scripts/backtest/backtest_pnl.py`) with
  autocorrelation-adjusted Sharpe.

---

## Pre-stable iteration history (selected snapshots)

- **2026-06-22**: GBPUSD promoted to portfolio (walk-forward IC 0.186).
- **2026-06-19**: BUY inversion evidence chain closed; risk-off suppression
  added for AUDUSD; bar-jump suppression added.
- **2026-06-19**: Regime model load-guard + missing-features bugs fixed
  (commits `f15af30`, `b980f69`).
- **2026-06-19**: Hurst constant zero-bug fixed via `raw=True` flag.
- **2026-06-17**: Position sizing guardrails added (drawdown taper, equity
  cap, risk cap, leverage budget, backstop).
- **2026-06-17**: Signal chatter + MT5 orphaned position fixes (5-fix chain).
- **2026-06-17**: THIN liquidity regime routed to soft warnings only.
- **2026-06-17**: Spreading gate, entry price deviation, profit lock gate
  each added as suppression stages.
- **2026-06-16**: SL/TP triple bug fixed
  (`_atr_barriers()` uses `atr_mult_tp`; `tp_compiler.py` caps R:R at 5.0).

---

## Documentation-affected-version table

| Doc | Authoritative source path | Last validated |
|---|---|---|
| `README.md` | n/a (top-level) | 2026-06-30 (audit) |
| `AGENTS.md` | n/a (operating guide) | 2026-06-30 (audit) |
| `LIVE_CONTRACT.md` | `paper_trading/config_manager.py` + `paper_trading/inference/models` | 2026-06-25 |
| `docs/SYSTEM_OVERVIEW.md` | `paper_trading/orchestrator/engine.py` | 2026-06-30 (audit) |
| `docs/PRODUCTION_SYSTEM_SPEC_v1.md` | n/a (production spec) | 2026-06-30 (supersedes v0) |
| `docs/FEATURES.md` | `features/alpha_features.py`, `features/regime_features.py` | 2026-06-26 |
| `docs/MODES.md` | `configs/paper_trading.yaml:modes` | 2026-06-30 (new) |
| `docs/SECURITY.md` | `paper_trading/serve.py`, `paper_trading/ops/mt5_client.py`, `paper_trading/config_manager.py` | 2026-06-30 (new) |
| `docs/STATE_INTERFACE.md` | `paper_trading/services/engine_state_service.py` | — (planned) |
| `docs/PEK_BUDGET.md` | `paper_trading/pek/*` | — (planned) |
| `docs/REPLAY.md` | `paper_trading/replay/{runner,wal}.py` | — (planned) |
| `docs/DASHBOARD_API.md` | `paper_trading/api/routes.py` | — (planned) |
| `docs/CHAOS_AND_FAULTS.md` | `tests/chaos/chaos_tools.py` | — (planned) |
| `docs/MT5_BRIDGE.md` | `paper_trading/ops/mt5_client.py`, `scripts/ops/mt5_bridge_supervisor.py` | — (planned) |
| `docs/METRICS_AND_ALERTING.md` | `eigencapital/observability/metrics.py`, `paper_trading/alerting/` | — (planned) |
