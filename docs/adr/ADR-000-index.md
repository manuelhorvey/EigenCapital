# ADR Index — EigenCapital

> **⚠ Historical Context Notice** — This ADR describes a research-stage decision that influenced system evolution. Some referenced components may no longer exist in the current production system.

Architecture Decision Records for the EigenCapital quantitative trading framework.

## Status Legend

- **Accepted** — Implemented and in use
- **Proposed** — Under review
- **Deprecated** — Superseded by a later ADR
- **Superseded** — Replaced by a newer ADR

## Index

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| 001 | [Triple Barrier Labeling Over Simple Directional Labels](ADR-001-triple-barrier-labeling.md) | Accepted | 2024-Q1 |
| 002 | [Regime Classifier as Router, Not Alpha Source](ADR-002-regime-classifier-as-router.md) | Accepted | 2024-Q1 |
| 003 | [Expanding Train Window Over Rolling for Walk-Forward](ADR-003-expanding-train-window.md) | Accepted | 2024-Q1 |
| 004 | [EURUSD Daily Rejected as Primary Asset](ADR-004-eurusd-rejected.md) | Accepted | 2024-Q2 |
| 005 | [Macro Expert Head With Protected Weight in Ensemble](ADR-005-macro-expert-head.md) | Accepted | 2024-Q2 |
| 006 | [XLF as Primary Equity Asset Over SPY/QQQ](ADR-006-xlf-primary-asset.md) | Accepted | 2024-Q2 |
| 007 | [Removed yield_slope and real_yield_10y From XLF Features](ADR-007-yield-slope-removed.md) | Accepted | 2024-Q2 |
| 008 | [Five-Year Training Window Over Three-Year](ADR-008-five-year-window.md) | Accepted | 2024-Q2 |
| 009 | [Accepted 150-250 Annual Trades for XLF](ADR-009-trade-count-accepted.md) | Accepted | 2024-Q2 |
| 010 | [Driver Atlas Framework — Asset-Specific Feature Sets](ADR-010-driver-atlas.md) | Accepted | 2024-Q3 |
| 011 | [EURUSD Blocked Pending COT Data Integration](ADR-011-eurusd-blocked.md) | Accepted | 2024-Q3 |
| 012 | [Three-Asset Portfolio — XLF, BTC, NZDJPY](ADR-012-three-asset-portfolio.md) | Accepted | 2024-Q3 |
| 013 | [Bootstrap Validation as Deployment Gate](ADR-013-bootstrap-validation.md) | Accepted | 2024-Q3 |
| 014 | [Zero Manual Overrides Policy During Paper Trading](ADR-014-zero-overrides-policy.md) | Accepted | 2024-Q4 |
| 015 | [Asset-Specific Label Horizons (tb20 vs fwd60)](ADR-015-asset-specific-label-horizons.md) | Accepted | 2025-Q1 |
| 016 | [GC=F Gold Validation](ADR-016-gold-validation.md) | Accepted | 2025-Q2 |
| 017 | [Inference Path Lookahead Investigation](ADR-017-inference-lookahead-investigation.md) | Accepted | 2026-05 |
| 018 | [BTC Satellite Isolation With Regime Gate](ADR-018-btc-satellite.md) | Accepted | 2026-05 |
| 019 | [Feature Importance Stability Tracking as Governance Signal](ADR-019-feature-importance-stability.md) | Accepted | 2026-05 |
| 020 | [Meta-Labeling Layer as Confidence Filter](ADR-020-meta-labeling.md) | Accepted | 2026-05 |
| 021 | [Simulation Snapshot System for Deterministic Replay](ADR-021-simulation-snapshot.md) | Accepted | 2026-05 |
| 022 | [Macro Expert Head Adaptive Weighting](ADR-022-macro-adaptive-weight.md) | Accepted | 2026-05 |
| 023 | [Fast Scale-Out Profit Taking and Dynamic SL/TP Calibration](ADR-023-fast-scale-out-calibration-scale.md) | Accepted | 2026-05 |
| 024 | [Macro Narrative Governance — Weekly LLM Overlay](ADR-024-macro-narrative-governance.md) | Accepted | 2026-05 |
| 025 | [Liquidity Regime Model — Volume/Amihud Proxy Governance](ADR-025-liquidity-regime-model.md) | Accepted | 2026-05 |
| 026 | [Regime-Conditional Ensemble Disabled](ADR-026-ensemble-disabled.md) | Accepted | 2026-06 |
| 027 | [Portfolio Execution Kernel — Centralized Admission Control](ADR-027-portfolio-execution-kernel.md) | Accepted | 2026-06 |
## By Topic

### Labeling & Signal
- ADR-001: Triple barrier labeling
- ADR-009: Accepted trade count

### Regime & Model Architecture
- ADR-002: Regime classifier as router
- ADR-005: Protected macro expert head
- ADR-022: Adaptive macro blend weight (online, bounded)

### Validation Methodology
- ADR-003: Expanding train window
- ADR-008: Five-year training window
- ADR-013: Bootstrap validation gate

### Asset Selection
- ADR-004: EURUSD rejected
- ADR-006: XLF over SPY/QQQ
- ADR-010: Driver atlas framework
- ADR-011: EURUSD blocked pending COT
- ADR-012: Three-asset portfolio

### Features
- ADR-007: Yield slope removed
- ADR-022 (operational): Lead-lag custom features via `lead_lag_edges.yaml` (see [HARDENING_ROADMAP.md](../HARDENING_ROADMAP.md))

### Risk & Monitoring
- ADR-018: BTC satellite isolation
- ADR-019: Feature importance stability tracking
- ADR-023: Fast scale-out and dynamic SL/TP calibration
- ADR-024: Macro narrative governance (weekly LLM overlay)
- ADR-025: Liquidity regime model (volume/Amihud proxy)
- ADR-027: Portfolio Execution Kernel (centralized admission control)

### Signal Processing
- ADR-020: Meta-labeling as confidence filter

### Infrastructure
- ADR-021: Simulation snapshot system
- HARDENING_ROADMAP: Three-tier isolation, execution physics, extended history

### Operations
- ADR-014: Zero manual overrides
