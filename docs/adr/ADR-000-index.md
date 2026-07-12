# ADR Index — EigenCapital

> **⚠ Historical Context Notice** — This ADR describes a research-stage decision that influenced system evolution. Some referenced components may no longer exist in the current production system.

Architecture Decision Records for the EigenCapital quantitative trading framework.

## Status Legend

- **Accepted** — Implemented and in use
- **Proposed** — Under review
- **Deprecated** — Superseded by a later ADR or overtaken by events
- **Superseded** — Replaced by a newer ADR
- **Obsolete** — Decision no longer relevant; implementation never occurred or architecture changed

## Index

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| 001 | [Triple Barrier Labeling Over Simple Directional Labels](ADR-001-triple-barrier-labeling.md) | Accepted | 2024-Q1 |
| 002 | [Regime Classifier as Router, Not Alpha Source](ADR-002-regime-classifier-as-router.md) | Deprecated (ADR-026) | 2024-Q1 |
| 003 | [Expanding Train Window Over Rolling for Walk-Forward](ADR-003-expanding-train-window.md) | Accepted | 2024-Q1 |
| 004 | [EURUSD Daily Rejected as Primary Asset](ADR-004-eurusd-rejected.md) | Accepted | 2024-Q2 |
| 005 | [Macro Expert Head With Protected Weight in Ensemble](ADR-005-macro-expert-head.md) | Deprecated (ADR-026) | 2024-Q2 |
| 006 | [XLF as Primary Equity Asset Over SPY/QQQ](ADR-006-xlf-primary-asset.md) | Deprecated | 2024-Q2 |
| 007 | [Removed yield_slope and real_yield_10y From XLF Features](ADR-007-yield-slope-removed.md) | Deprecated | 2024-Q2 |
| 008 | [Five-Year Training Window Over Three-Year](ADR-008-five-year-window.md) | Accepted | 2024-Q2 |
| 009 | [Accepted 150-250 Annual Trades for XLF](ADR-009-trade-count-accepted.md) | Deprecated | 2024-Q2 |
| 010 | [Driver Atlas Framework — Asset-Specific Feature Sets](ADR-010-driver-atlas.md) | Accepted | 2024-Q3 |
| 011 | [EURUSD Blocked Pending COT Data Integration](ADR-011-eurusd-blocked.md) | Superseded (ADR-011a) | 2024-Q3 |
| 011a | [EURUSD Unblocked — COT Integration Complete](ADR-011a-eurusd-unblocked.md) | Accepted | 2025-Q1 |
| 012 | [Three-Asset Portfolio — XLF, BTC, NZDJPY](ADR-012-three-asset-portfolio.md) | Superseded | 2024-Q3 |
| 013 | [Bootstrap Validation as Deployment Gate](ADR-013-bootstrap-validation.md) | Accepted | 2024-Q3 |
| 014 | [Zero Manual Overrides Policy During Paper Trading](ADR-014-zero-overrides-policy.md) | Accepted | 2024-Q4 |
| 015 | [Asset-Specific Label Horizons (tb20 vs fwd60)](ADR-015-asset-specific-label-horizons.md) | Superseded | 2025-Q1 |
| 016 | [GC=F Gold Validation](ADR-016-gold-validation.md) | Accepted | 2025-Q2 |
| 017 | [Inference Path Lookahead Investigation](ADR-017-inference-lookahead-investigation.md) | Accepted (Investigation) | 2026-05 |
| 018 | [BTC Satellite Isolation With Regime Gate](ADR-018-btc-satellite.md) | Obsolete | 2026-05 |
| 019 | [Feature Importance Stability Tracking as Governance Signal](ADR-019-feature-importance-stability.md) | Accepted | 2026-05 |
| 020 | [Meta-Labeling Layer as Confidence Filter](ADR-020-meta-labeling.md) | Deprecated | 2026-05 |
| 021 | [Simulation Snapshot System for Deterministic Replay](ADR-021-simulation-snapshot.md) | Accepted | 2026-05 |
| 022 | [Macro Expert Head Adaptive Weighting](ADR-022-macro-adaptive-weight.md) | Deprecated (ADR-026) | 2026-05 |
| 023 | [Fast Scale-Out Profit Taking and Dynamic SL/TP Calibration](ADR-023-fast-scale-out-calibration-scale.md) | Accepted | 2026-05 |
| 024 | [Macro Narrative Governance — Weekly LLM Overlay](ADR-024-macro-narrative-governance.md) | Accepted | 2026-05 |
| 025 | [Liquidity Regime Model — Volume/Amihud Proxy Governance](ADR-025-liquidity-regime-model.md) | Accepted | 2026-05 |
| 026 | [Regime-Conditional Ensemble Disabled](ADR-026-ensemble-disabled.md) | Accepted | 2026-06 |
| 027 | [Portfolio Execution Kernel — Centralized Admission Control](ADR-027-portfolio-execution-kernel.md) | Accepted | 2026-06 |
## By Topic

### Labeling & Signal
- ADR-001: Triple barrier labeling
- ADR-009: Accepted trade count (deprecated — superseded by PEK admission)
- ADR-015: Asset-specific label horizons (deprecated — now per-asset ATR-based pt_sl)
- ADR-020: Meta-labeling as confidence filter (deprecated — now XGBoost-based)

### Regime & Model Architecture
- ADR-002: Regime classifier as router (deprecated — ensemble disabled)
- ADR-005: Protected macro expert head (deprecated — ensemble disabled)
- ADR-022: Adaptive macro blend weight (deprecated — ensemble disabled)
- ADR-026: Regime-conditional ensemble disabled (current)

### Validation Methodology
- ADR-003: Expanding train window
- ADR-008: Five-year training window
- ADR-013: Bootstrap validation gate

### Asset Selection
- ADR-004: EURUSD rejected
- ADR-006: XLF over SPY/QQQ (deprecated — XLF removed from portfolio)
- ADR-010: Driver atlas framework
- ADR-011: EURUSD blocked pending COT
- ADR-012: Three-asset portfolio (superseded — now 22-asset portfolio)

### Features
- ADR-007: Yield slope removed (deprecated — XLF removed; yield_slope still used for GC)

### Execution
- ADR-023: Fast scale-out and dynamic SL/TP calibration (updated — superseded by adaptive exit engine 2026-07-10)
- ADR-027: Portfolio Execution Kernel (centralized admission control)

### Risk & Monitoring
- ADR-018: BTC satellite isolation (obsolete — BTC actively traded in 22-asset portfolio)
- ADR-019: Feature importance stability tracking
- ADR-024: Macro narrative governance (weekly LLM overlay)
- ADR-025: Liquidity regime model (volume/Amihud proxy)

### Infrastructure
- ADR-021: Simulation snapshot system

### Operations
- ADR-014: Zero manual overrides
