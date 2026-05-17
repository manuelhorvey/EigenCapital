# ADR Index — QuantForge

Architecture Decision Records for the QuantForge quantitative trading framework.

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

## By Topic

### Labeling & Signal
- ADR-001: Triple barrier labeling
- ADR-009: Accepted trade count

### Regime & Model Architecture
- ADR-002: Regime classifier as router
- ADR-005: Protected macro expert head

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

### Operations
- ADR-014: Zero manual overrides
