# EigenCapital — Agent Operating Guide

This document is the entry point for the EigenCapital system. It has been split into three focused documents for easier navigation.

> **Note for AI agents**: When starting a new task, read the relevant sub-document(s) below instead of this entry point.

---

## 📋 [Operations Runbook →](docs/OPERATIONS.md)

**For operators running the system day-to-day.**

Includes:
- Quick start and common task commands
- Go/No-Go checklist (paper trading → live)
- Security configuration
- Position sizing chain reference
- Known issues (active and historical)
- Logging and debugging guide

---

## 🏗️ [Architecture Reference →](docs/ARCHITECTURE_REFERENCE.md)

**For developers understanding the system design.**

Includes:
- Architecture overview (models, features, labels)
- Portfolio Maturity Framework (P0–P4)
- PEK (Portfolio Execution Kernel) components
- Orchestrator 5-phase cycle diagram
- 25-stage governance decision pipeline
- Key files index
- MT5 Bridge design
- Structural limitations (permanent)
- ADR index (27 records)

---

## 📚 [Research History →](docs/RESEARCH_HISTORY.md)

**For understanding past investigations and decisions.**

Includes:
- Walk-Forward PnL Backtest methodology and results
- BUY Inversion Discovery and SHAP Audit
- Adaptive Exit Engine design and validation
- Monte Carlo simulations and stress tests
- Feature engineering evolution
- Asset timeline (additions, removals, filter changes)

---

## Quick Reference

### Project Identity

Cross-sectional multi-asset paper trading engine. 22-asset portfolio (FX, commodities, indices + BTCUSD) with per-asset XGBoost models, 17-layer governance + 3 adaptive budget layers, PEK admission control, and MT5 bridge execution.

### Key Commands

```bash
# Run paper trading
PYTHONPATH=$PYTHONPATH:. python paper_trading/ops/monitor.py

# Retrain all assets
PYTHONPATH=$PYTHONPATH:. python scripts/training/retrain_all_fixed.py

# PnL backtest
PYTHONPATH=$PYTHONPATH:. python scripts/backtest/backtest_pnl.py

# Check state
curl http://127.0.0.1:5000/state.json | python3 -m json.tool
```

### Key Conclusions

- **Ensemble disabled** — base_weight=1.0 portfolio-wide (see ADR-026). Regime features still computed for trace logging.
- **SELL_ONLY** — 6 permanent assets (CADCHF, EURAUD, EURCHF, GBPCHF, GBPJPY, NZDCHF). See `paper_trading/execution/gate_constants.py`.
- **Adaptive exit engine** — 4-stage retracement trailing. Config per asset.
- **Factor constraints** — `factor_constrained_v2` with hard linear inequality constraints, pinning CHF at 20%.
- **Drift detector** — live win-rate drift against breakeven WR; dashboard at `/optimization.json`.
- **Doc-drift CI check** — `tools/doc_drift_check.py` runs 14 cross-reference checks in CI.

### Related Documentation

| Document | Purpose |
|----------|---------|
| `docs/OPERATIONS.md` | Day-to-day operations |
| `docs/ARCHITECTURE_REFERENCE.md` | System design and components |
| `docs/RESEARCH_HISTORY.md` | Past investigations and decisions |
| `docs/FEATURES.md` | Feature taxonomy |
| `docs/SYSTEM_OVERVIEW.md` | System overview |
| `docs/GOVERNANCE.md` | Governance layers |
| `docs/adr/ADR-000-index.md` | Architectural Decision Records |

---

*Last updated: 2026-07-18. Kept intentionally concise — see linked documents above for depth.*
