# Dashboard & Observability Contract

**Status:** GOVERNING · **Created:** 2026-09-25 · **Authority:** Phase 1 full-system audit (`docs/audits/FULL_SYNC_DASHBOARD_AUDIT_2026-09-25.md`)
**Supersedes:** conflicting dashboard guidance in historical audit docs (historical docs are records, not current status).
**Change control:** any deviation from this contract requires a dated amendment to this document — not a code-first change.

---

## 1. Non-negotiable principle

> **The dashboard is a window into EigenCapital, not a second EigenCapital.**

The dashboard is a read-only observability layer. It never creates, modifies, or fabricates trading state. Every displayed value must trace to an authoritative backend source; every displayed state must be backed by evidence at least as strong as the claim.

## 2. Truthfulness — hard acceptance criteria

A dashboard change is rejected if any of the following is true:

1. **T1 — No unbacked lifecycle states.** UI must not render lifecycle steps (Signal → Target → Risk → Order → Fill → Position) unless each step is derived from actual per-ticket / per-event backend data. A visually asserted chain that no query produces is fabrication.
2. **T2 — No proxy checks presented as actual checks.** A gate/badge must reflect the dimension it names (e.g. a "Watchdog" chip must read watchdog state, not a generic `status === "ok"` flag; a "Broker" chip must read broker connectivity, not account freshness).
3. **T3 — Unknown ≠ zero.** Missing data renders as NOT AVAILABLE / STALE / UNKNOWN. No numeric `0` fallback for a value that was never observed. Zero is a measurement; unavailability is a state.
4. **T4 — No UI claim stronger than its backend evidence.** LIVE only when freshness is LIVE; "protected" only from SL presence (current source); research labels only from the research registry. Research output must never be rendered as production capability, and production capability must never be rendered as research.
5. **T5 — Stale states are explicit.** Stale data shows its age. "Real-time" is claimed only for genuinely streamed, authenticated transports.

## 3. Data-lineage requirement

Every important visual must trace:

```
UI component → API endpoint → backend service → canonical model → underlying source
```

The authoritative lineage matrix lives in `docs/production/DASHBOARD_DATA_TRUTH_MATRIX.md` (regenerated 2026-09-25). A new dashboard component without a lineage row is incomplete. The matrix documents, per metric: component, endpoint, DTO, service method, authoritative source, units, precision, freshness semantics, and fallback behavior.

## 4. Single writer / single owner (project-wide rule)

Every persisted state file has exactly one writer, which is its owner:

| File | Owner (sole writer) | Dashboard role |
|---|---|---|
| `reports/r4_loop/risk_state.json` | Live rebalance loop / RiskEnforcer | Read-only |
| `reports/r4_loop/supervisor_state.json`, `loop_health.json` | Supervisor / monitor | Read-only |
| `reports/r4_loop/reconciliation_state.json` | Reconciliation engine | Read-only |
| `reports/r4_qualification/qualification_status.json` | Evidence pipeline | Read-only |

**The dashboard service computes fallback values in memory for display but must not persist them.** A competing writer produces ambiguous provenance and can overwrite loop-authored state with dashboard-scoped constants. Derived-only files created by the dashboard for its own caching must live in a dashboard-owned path and be labeled as such.

## 5. Dashboard ↔ research boundary

Volatility taxonomy / trade-path research (`docs/research/VOLATILITY_TAXONOMY_RESEARCH.md`, `research/volatility/`, `reports/volatility_taxonomy/`) is **descriptive/diagnostic** and is not a production citation. The dashboard may display research registry state (verdicts, trial slots, program status) only under an explicit research label sourced from `reports/research_program/program_status.json` / `docs/research/RESEARCH_PROGRAM_STATUS.md`. Research visualizations must never become operational signals, and no dashboard metric may create implied production recommendations.

## 6. Production universe adjudication — USOIL

**Adjudicated 2026-09-25: USOIL is production-admitted** for the current campaign as a tradeable `[broker.allowed_symbols]` entry (`configs/production/config.toml`, class `energy`; min-lot fits the $5K position envelope).

The frozen research document `docs/research/VOLATILITY_TAXONOMY_RESEARCH.md` §3 states USOIL is "external candidates only — never production." That statement is **scoped to the research baseline** (`vol_taxonomy_v1` frozen 34-asset ASSET_CLASSES dict) and does not govern the production universe. The frozen research document is **not modified** by this adjudication; the production universe authority remains `configs/production/config.toml` per `docs/DOCUMENTATION_SOURCE_OF_TRUTH.md`.

Future asset-admission questions follow the same pattern: the production universe is governed by production config + governance docs, the research baseline by frozen research records, and neither silently overrides the other.

## 7. Master-prompt addendum (for future agent work)

When directing agent work on EigenCapital, use this order and these constraints:

> **"Synchronize first, eliminate fabricated semantics second, consolidate the design system third, then perform an evidence-based premium refinement without changing the underlying information architecture."**

- Phase A — Synchronization: docs vs code vs API (regenerate truth matrices; fix broken references).
- Phase B — De-fabrication: enforce §2 truthfulness criteria (T1–T5).
- Phase C — Consolidation: single status-color mapping, centralized numeric formatting, one freshness vocabulary.
- Phase D — Premium refinement: evidence-based visual polish; **do not** redesign the information architecture (verdict: B — Refine per audit §12).
- Always: no trading-logic changes; no research-governance bypass; single-writer rule enforced; lineage rows required for new visuals.

## 8. Frontend engineering requirements (added to acceptance)

1. **Visual consistency is an engineering requirement:** one status-color mapping module; one numeric formatting module (percent/currency/price/quantity/R/bps/timestamps/durations); consistent decimal precision per metric class.
2. **Lineage comments:** components displaying authoritative state declare their endpoint in code (e.g. adjacent to the query) matching the truth-matrix row.
3. **Transport truth:** the live transport (WebSocket) must be authenticated; polling endpoints must not be labeled "real-time" in UI copy.
4. **API key injection:** `VITE_API_KEY` is inlined into the frontend bundle at build time and must match the backend `DASHBOARD_API_KEY` (it authenticates both REST Bearer calls and the `/ws/live?token=` handshake). It is therefore a *network-boundary* secret, not a user secret: production deployments must serve the dashboard behind a trusted network/reverse proxy and inject the key at build/deploy time (see `.env.example`). The `dev-key-change-in-production` fallback is for local development only.
