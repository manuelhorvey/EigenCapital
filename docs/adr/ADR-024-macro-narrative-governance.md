# ADR-024 — Macro Narrative Governance (Weekly LLM Overlay)

**Status:** Accepted  
**Date:** 2026-05  
**Tags:** governance, risk, llm, narrative

## Context

The system has strong execution-layer governance (validity state machine, meta-labeling, feature stability) but no macro context layer. The XGBoost model processes structured macro data (yields, VIX, DXY) as features, but it cannot interpret unstructured macro narrative signals — geopolitical events, central bank tone shifts, energy crisis risk — that are expressed in text before they materialize in price.

## Decision

Add a weekly LLM-driven macro narrative pipeline as an execution governance overlay (Track A — governance only, no training pipeline changes).

### Design

- **Source**: FXStreet "Week ahead" article (weekly macro roundup)
- **LLM**: Claude API (`claude-sonnet-4-20250514`) via `features/fxstreet_fetcher.py`
- **Output**: `MacroNarrativeFeatures` dataclass with `geopol_risk_score`, central bank hawkishness scores, currency biases, `overall_regime`, `confidence`
- **Governance rules** (`narrative_governance_scalars()`):
  - `geopol_risk_score > 0.7` → SL widens by configurable pct (default +10%)
  - `overall_regime == "risk_off"` → position size reduces (default -20%)
  - `confidence < min_confidence` (0.6) or stale → no governance applied
- **Human review step**: Output lands as `narrative_pending.json`; one-click confirm via dashboard; auto-confirm at Monday noon
- **Staleness**: ≥7 days → flag suppresses governance
- **Integration**: `_narrative_sl_mult` in SL chain; `_narrative_size_scalar` in sizing notional; `narrative_ok` halt flag with -0.10 validity penalty

### Key Constraints

1. Governance overlay only — no feature registration, no builder changes, no XGBoost retraining (Track A before Track B)
2. Conservative governance knobs to start (SL widen, size reduce only)
3. Automated pipeline + human confirmation (prevents LLM hallucinations from affecting live execution without review)
4. Stale narrative carries forward with visible staleness flag; fetch/LLM errors surface as warning badge, not silent degrade
5. `narrative_version` field (hash of source text) for audit trail

## Consequences

**Positive:**
- System gains macro context awareness without retraining models
- Weekly cadence matches macro narrative release schedule
- Human review step provides safety layer against LLM errors
- Dashboard visibility into governance state

**Negative:**
- FXStreet HTML changes can break scraper without notice
- LLM extraction is non-deterministic — same article may produce different scores
- Requires ANTHROPIC_API_KEY env var
- Adds operational complexity (Monday morning check required)

## Validation

First Monday of operation will verify:
1. Scrape reliability — fetch_error rate
2. LLM JSON compliance — neutral default fallback on malformed response
3. Auto-confirm rate — whether deadline is consistently met
4. Governance frequency — how often geopol_risk_score > 0.7 triggers
