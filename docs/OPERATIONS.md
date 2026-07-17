# EigenCapital — Operations Runbook

Operational commands, common tasks, health checks, and troubleshooting.

**Last updated:** 2026-07-17

---

## Quick Start

```bash
# Run paper trading (monitor + dashboard, ~60s refresh interval)
PYTHONPATH=$PYTHONPATH:. python paper_trading/ops/monitor.py

# Full launcher (MT5 + Dashboard + Slack Alerter)
./monitor_all

# Check dashboard state
curl http://127.0.0.1:5000/state.json | python3 -m json.tool
```

---

## Common Tasks

### Run Paper Trading
```bash
PYTHONPATH=$PYTHONPATH:. python paper_trading/ops/monitor.py
```

### Slack Alerter (optional, requires SLACK_WEBHOOK_URL env var)
```bash
PYTHONPATH=$PYTHONPATH:. python paper_trading/ops/slack_alerter.py
```

### Retrain All Assets
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/training/retrain_all_fixed.py
```

### Train Regime Models
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/training/train_regime_models.py
```

### Walk-Forward Backtest (10-year data)
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/analysis/run_expanded_walkforward_v2.py
# Then backtest with production thresholds:
PYTHONPATH=$PYTHONPATH:. python scripts/backtest/backtest_pnl.py --tag expanded_10yr --use-prod-thresholds --calibrate
```

### Walk-Forward Backtest (diagnostic, per-asset)
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/backtest/walk_forward_backtest.py --asset GBPCAD --expanded-dir auto
```

### PnL Backtest from Signal Parquets
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/backtest/backtest_pnl.py
```

### PnL Backtest with Weight Strategy
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/backtest/backtest_pnl.py --weight-method factor_constrained_v1
```

### Compare Ensemble vs Base
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/backtest/backtest_pnl.py --tag base --ensemble-tag ensemble
```

### Train Calibration Models
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/training/train_calibration.py
```

### Reconstruct Historical Portfolio Weights
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/replay/replay_rebalance.py --verify
```

### Daily Monitoring
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/ops/monitor_paper_trading.py
```

---

## Production Trade Lifecycle Audit

**Script**: `scripts/analysis/production_audit.py`
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/analysis/production_audit.py --output data/processed/audits/full_audit_results.json
```

**Architecture**: `scripts/analysis/audit_phases/` — 16 phase modules + orchestrator.
- Phase 0 (`phase_data.py`): augments trades with temporal metadata, defines shared constants
- Phases 1–17: independent forensics
- Phase 18: aggregates and scores

**Latest results** (2026-07-02): 15 phases, 11 recommendations.

---

## Go/No-Go Checklist (Paper Trading → Live)

| Check | Target | Source |
|-------|--------|--------|
| Gate override rate | <40% all assets | monitor csv |
| Mean confidence | >0.52 for ≥14/16 | monitor csv |
| Signal flips | ≤3/day for ≥14/16 | monitor csv |
| Cross-asset correlation | no unexplained >0.7 | monitor csv |
| MT5 errors | zero | engine logs |
| Trades executed | ≥10 across portfolio | MT5 terminal |

**Decision**: 6/7 pass → go live at 50% position size for 2 weeks, then full size if live Sharpe tracks within 0.2 of backtest Sharpe.

---

## Security

The dashboard HTTP server (`paper_trading/serve.py`) supports bearer-token authentication.

- **Config**: Set `EIGENCAPITAL_API_TOKEN` env var, or `api_token` in `configs/domains/infrastructure/config.yaml`. Env var takes precedence.
- **Behavior**: If a token is configured, all JSON API endpoints and POST endpoints require `Authorization: Bearer <token>`. Static files (HTML/CSS/JS) are accessible without auth.
- **Non-loopback binding**: Auth is **mandatory** if binding to anything other than 127.0.0.1. The server will refuse to start without a token.
- **Default**: No token configured = open access (safe because the server binds to 127.0.0.1 by default).
- **Bind address**: Override with `EIGENCAPITAL_BIND` env var.
- **CORS**: Restricted to `http://127.0.0.1:3000` (Vite dev server) and same-origin. No wildcard.
- **Secrets**: MT5 credentials can be stored in HashiCorp Vault KV v2. Set `VAULT_ENABLED=1` and configure `VAULT_ADDR`, `VAULT_TOKEN`, `VAULT_SECRET_PATH`. Falls back to env vars (`MT5_ACCOUNT`, `MT5_PASSWORD`, `MT5_SERVER`) when Vault is unavailable.

---

## Position Sizing Chain

Paper positions are sized through multiplicative guardrails:

```
effective_cap = capital_base × min(mtm / initial_capital, 3.0)
size_scalar = base × exposure × governance × meta
notional = effective_cap × size_scalar
→ drawdown taper (linear 1.0→min between start_dd/end_dd)
→ cap by max_position_pct_of_equity
→ cap by risk_per_trade_pct (skip if below min_viable_position_pct)
→ PEK budget enforcement (Phase 1b — closes lowest-ranked if portfolio notional
  exceeds max_leverage × equity × tolerance)
```

**Kelly multiplier (P2, disabled by default):**
```
size_scalar = base × kelly_multiplier × exposure × governance × meta × drawdown_taper
```
Where `kelly_multiplier = compute_kelly_multiplier(calibrated_prob, tp_mult, sl_mult)`.

**PEK budget enforcement (Phase 1b):**
If total portfolio notional exceeds `max_leverage × equity × tolerance`, the lowest-ranked admitted positions are closed by `_phase_1b_admission_review()`.

MT5 positions are sized independently:
```
mt5_equity = broker.get_account_summary().portfolio_value
notional = mt5_equity × max_position_pct_of_equity × drawdown_taper
→ cap by risk_per_trade_pct (skip if below min_viable)
→ validate min volume via _quantity_to_lots()
```

Log lines: `SIZING` (paper) and `MT5_SIZING` (MT5) with all decomposed factors.

---

## Known Issues

### Current Active Issues

- **Small MT5 equity ($107 demo)**: 0.01 lot minimum for forex (≈$1,150 notional on EURUSD) far exceeds the MT5 position budget (≈$15.67 at 15% of $104). MT5 positions quantize to 0.01 lots regardless of computed size. Revisit when equity > $10K.
- **NZDCAD/NZDUSD confidence gate (PROPOSED 2026-06-23, not implemented)**: NZDCAD and NZDUSD show 92-96% confidence every cycle with no win-rate data. Add check once either asset reaches n_trades >= 20.

### Fixed / Historical Issues

| Date | Issue | Fix |
|------|-------|-----|
| 2026-07-03 | Emergency halt loop (BTC weekend) | Moved cycle counter, re-anchor peak at init, auto-clear on restart |
| 2026-06-25 | WAL os.fsync exception gap | Already wrapped in try/except — no action needed |
| 2026-06-23 | Position concentration alert | Implemented WAL event + slack alerter |
| 2026-06-22 | NQ price deviation gate blocking entries | per-asset max_entry_slippage_pct: 5.0 |
| 2026-06-22 | Return computation denominator | Fixed capital_base baseline |
| 2026-06-19 | Regime model at inference (2 bugs) | Load guard fix + missing features fix |
| 2026-06-19 | Spread gate | Added apply_spread_gate |
| 2026-06-19 | pipeline.py indentation nesting | Fixed module-level method misplacement |
| 2026-06-19 | Signal chatter + MT5 orphaned positions | Stability filter + hysteresis + cool-down |
| 2026-06-19 | Risk-off consequence validated | AUDUSD risk-off suppression |
| 2026-06-19 | Bar-jump suppression | 60-min trading halt on data-source switch |
| 2026-06-19 | Carry feature always zero | Fixed column name in rate_diffs |
| 2026-06-19 | Ensemble breakdown logger column prefix | Fixed CLOSE_ prefix |
| 2026-06-17 | Position sizing guardrails | drawdown taper, equity cap, risk cap |
| 2026-06-17 | Profit lock gate | Blocks flips when PnL > 15% |
| 2026-06-17 | Entry price deviation gate | Skips if deviation > max_entry_slippage_pct |
| 2026-06-17 | Prob drift min samples | 3 → 10 |
| 2026-06-17 | THIN liquidity | STRESSED halts only; THIN → soft_warnings |
| 2026-06-16 | SL/TP triple bug | atr_mult_tp, uncalibrated SL, TP convexity |

---

## Logging & Debugging

- **Engine log**: `data/live/engine.log` (rotated at 10 MB, 5 backups)
- **JSON stream**: stdout (for log aggregators)
- **Trace log**: `data/live/trace.jsonl`
- **WAL events**: `data/live/wal/YYYY-MM-DD/engine.jsonl`
- **State snapshot**: `data/live/state.json`
- **Correlation IDs**: All log lines include `[correlation_id]` for request tracing
