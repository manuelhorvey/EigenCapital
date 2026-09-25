# EigenCapital — Full Synchronization, Research & Dashboard Audit

**Date:** 2026-09-25 · **Type:** Phase 1 audit only (no code, config, or trading behavior modified)
**Scope:** System spec → contracts → data → features → research → strategy → portfolio → risk → execution → API → dashboard → documentation
**Verification evidence collected during audit:** `tests/unit/dashboard` 97 passed · `tests/unit/research/volatility` 48 passed · `mypy src/eigencapital/dashboard` clean (25 files) · `tsc -b` (dashboard) clean · `.env` confirmed gitignored.

---

## 1. Executive Summary

The repository tells a **coherent and unusually disciplined story**. Research governance (R0–R8 frozen queue, exact verdict vocabulary, production-boundary rules) is enforced by documents *and* by tests; the dashboard is a genuinely read-only observer with DTO contracts, freshness semantics, and contract tests; the README's status table matches `PHASE_STATUS.md` and the config.

The system is **not fully synchronized**, however. The dominant findings:

1. **`DASHBOARD_DATA_TRUTH_MATRIX.md` was stale and misleading** — it documented as *current known issues* several defects the code has since fixed (`daily_pnl`, `unrealized_pnl`, health `dimensions`, position `risk_state`, MAE/MFE, `fingerprint_status`). [Fixed in Phase 2 — matrix regenerated 2026-09-25.]
2. **The Positions lifecycle strip fabricated certainty** — SIGNAL→ORDER→FILL→POSITION→RISK rendered as completed for every position from a hardcoded array, with no per-ticket backend source. [Fixed in Phase 2 — strip removed per contract T1.]
3. **Alerts ordering bug** — newest-first sort then `[-limit:]` returned the *oldest* slice; "Recent Alerts" showed stale items. [Fixed in Phase 2 with regression test.]
4. **WebSocket `/ws/live` was unauthenticated** and ran one full-state MT5 poll loop *per connection* with O(N²) broadcast — while the frontend never actually used WS data (dual-transport drift). [Fixed in Phase 2 — auth + shared broadcaster + cached state.]
5. **Drawdown gauge unit mismatch + zero-fallback** — fraction (0–1) rendered as "%"; missing data rendered as 0%. [Fixed in Phase 2 — percent scaling + explicit no-data state.]
6. **Universe contradiction** — production `config.toml` lists `USOIL` as tradeable; the frozen volatility-taxonomy doc says USOIL is "external candidates only — never production." [Adjudicated 2026-09-25: USOIL is production-admitted; research doc untouched — see `DASHBOARD_CONTRACT.md` §6.]

**Dashboard redesign verdict: B — Refine.** Architecture and design system are sound (token system, read-only lineage, status semantics, a11y foundations). The failures were specific fabrications, stale docs, and semantic mislabels — not structural rot. A redesign would preserve problems; targeted fixes do not.

---

## 2. Architecture Map (current, verified)

```
configs/production/config.toml (strategy/risk/universe authority)
        ↓
scripts/r4_rebalance_loop.py  ── live loop, signal → portfolio → RiskPolicy gates → MT5 orders
        ↓                         writes reports/r4_loop/*.jsonl|json (decisions, health, risk, recon)
src/eigencapital/live/*       ── risk_enforcement (RiskEnvelope), risk_observation (RiskObserver),
                                 watchdog, supervisor, position_attribution, catastrophic_protection,
                                 durable_audit, build_pinning
        ↓
src/eigencapital/dashboard/
  services/dashboard_state.py ── read adapter: MT5 (mt5linux) + reports/ files + RiskEnvelope
  schemas/*                   ── Pydantic DTOs (Account, Position, Risk, Health, Evidence, Recon, Alert)
  api/routes/*                ── FastAPI GET-only routes under /api/v1 (+ /ws/live, /healthz)
  streaming/events.py         ── WebSocket + SSE (authenticated — fixed per F-04)
        ↓
dashboard/src (React 19 + Vite + TanStack Query + Tailwind v4 tokens)
  lib/api.ts (typed client, Bearer key) · lib/dataState.tsx (LIVE/STALE/UNKNOWN) · pages/* · ui/*
```

Entry points: `scripts/r4_rebalance_loop.py` (live), `scripts/r4_monitor.py`, dashboard API (`uvicorn eigencapital.dashboard.api.app:app`, port 8080), dashboard SPA (`vite`, 5173, proxy `/api` + `/ws` → 8080).

---

## 3. Source-of-Truth Map (verified against `DOCUMENTATION_SOURCE_OF_TRUTH.md`)

| Concept | Canonical owner | Status |
|---|---|---|
| Strategy identity/params | `configs/production/config.toml` `[strategy]` + `r4_manifest.py` | ✅ synchronized |
| Live risk envelope | `[live_risk]` → `RiskEnvelope.from_config()` | ✅ |
| General risk policy | `[risk]` → `risk/policy.py` | ✅ (strictly looser; documented) |
| Universe | `[broker.allowed_symbols]` (35 entries, 7 `forex_excluded` → 28 tradeable) | ✅ (USOIL adjudicated, contract §6) |
| Research verdicts | `RESEARCH_PROGRAM_STATUS.md` + guarded `program_status.json` | ✅ |
| Dashboard account/positions | MT5 via `DashboardStateService` | ✅ |
| Dashboard risk state | `risk_state.json` (**loop-only writer**) or RiskObserver live-compute | ✅ (single-writer enforced) |
| Dashboard health | `loop_health.json`/`supervisor_state.json` + derived dimensions | ✅ |
| Events | `reports/r4_loop/decisions.jsonl` | ✅ |
| Alerts | `alerts.jsonl` + `monitor.jsonl` | ✅ (ordering fixed) |
| **Dashboard data truth** | `DASHBOARD_DATA_TRUTH_MATRIX.md` | ✅ (regenerated 2026-09-25) |

---

## 4. Synchronization Findings

| ID | Finding | Class | Sev | Status |
|---|---|---|---|---|
| F-01 | `DASHBOARD_DATA_TRUTH_MATRIX.md` (audited 2026-08-29) listed as *current* issues: `daily_pnl` hardcoded 0, `unrealized_pnl` hardcoded 0, health `dimensions` always empty, position `risk_state` always NORMAL, MAE/MFE always None, `fingerprint_status` always VERIFIED. Code now computes all of these. | STALE / MISLEADING | P1 | **Fixed** — matrix regenerated 2026-09-25 |
| F-02 | `DASHBOARD_API.md` incomplete: omits `/alerts`, `/reconciliation`, `/health/authorization`, `/health/watchdog`, `/portfolio/summary`; several response examples outdated. | INCOMPLETE | P2 | **Fixed** — all `/api/v1` endpoints documented, examples corrected, error-semantics table added (2026-09-25) |
| F-03 | **Alert ordering bug**: `get_recent_alerts()` sorted newest-first then returned `alerts[-limit:]` → returned the *oldest* of the recent set. | BUG | P1 | **Fixed** + regression test |
| F-04 | **WS auth gap**: HTTP middleware auth did not cover WebSocket; `/ws/live` streamed full account/position/risk state with no key; per-connection poll loops (O(N) MT5 load, O(N²) broadcast). | SECURITY | P1 | **Fixed** — token auth (1008 on failure) + one shared broadcaster + cached state |
| F-05 | Positions detail "Lifecycle" rendered a hardcoded always-complete step list (SIGNAL→ORDER→FILL→POSITION→RISK) — §32 fabrication class. | FABRICATION | P1 | **Fixed** — strip removed (contract T1) |
| F-06 | Overview gate strip used proxies: `Broker: ok = account.freshness==="LIVE"`, `Watchdog: ok = health.status==="ok"`, `Data: ok = risk.freshness ∈ {LIVE,STALE}`. | MISLEADING | P2 | **Fixed** (in P1 pass) — chips now read actual `/health` dimensions; unknown renders neutral, not green |
| F-07 | `evidence.py` events route: `newest_timestamp=parsed[0]`, `oldest_timestamp=parsed[-1]` — decisions.jsonl is chronological, so the labels are swapped. | BUG (minor) | P2 | **Fixed** — labels corrected to match chronological ledger (2026-09-25) |
| F-08 | Evidence gates: backend emits `SUFFICIENT`/`COLLECTING`; frontend renders only `PASS`/`FAIL` → gates never reach a terminal visual state. | CONTRACT MISMATCH | P2 | **Fixed** — gate rendering handles SUFFICIENT/COLLECTING/FAIL/unknown with honest states (2026-09-25) |
| F-09 | Overview "Closed Trades" showed `e0_count` (signal-level evidence count); the closed-trade analog is `completed_lifecycles`. | MISLABEL | P2 | **Fixed** (in P1 pass) |
| F-10 | **Universe contradiction**: `config.toml` `USOIL="energy"` vs frozen `VOLATILITY_TAXONOMY_RESEARCH.md` §3 "USOIL … never production". | CONTRADICTION | P1 | **Adjudicated** — production-admitted; contract §6; research doc untouched |
| F-11 | `risk_state.json` had two writers: the live loop and the dashboard service's live-compute fallback (persisted its result). | DUPLICATE SOURCE | P2 | **Fixed** — dashboard no longer persists |
| F-12 | `dashboard_state.py` hardcoded `max_concentration_pct=0.30`, `max_margin_utilization=0.80` in the RiskObserver fallback — dashboard-owned risk constants outside config authority. | DUPLICATED LOGIC | P2 | **Fixed** (in P1 pass) — RiskObserver defaults used; regression-tested |
| F-13 | `AccountDTO.daily_loss_remaining` defaults to `250` in the schema (magic number) even though the service supplies the envelope value. | STALE DEFAULT | P2 | **Fixed** — schema default is now `0` (= unavailable, unknown ≠ zero); service supplies the envelope value (2026-09-25) |
| F-14 | Risk page dimension rows formatted raw `value` (2dp) with no units; gauge treated fraction as `%` and fell back to `0` when data was missing (unknown ≠ zero violation). | UNIT/SEMANTICS | P1 | **Fixed** — `formatObsValue` unit map; percent-scaled gauge; explicit no-data state |
| F-15 | Terminology bleed: `get_system_health` treated `"NORMAL"` as a health overall-state (risk vocabulary). | VOCABULARY | P3 | **Fixed** — health overall-state vocabulary is HEALTHY/DEGRADED/HALTED/UNKNOWN only; `system.py` status mapping updated; vocabulary comment added (2026-09-25) |
| F-16 | Overview passed `account.timestamp` as the freshness timestamp for all six metrics (including Positions/Risk). | MISLEADING | P2 | **Fixed** (in P1 pass) — per-metric timestamps |

---

## 5. Research Governance Findings

- Queue state (R0–R8), verdict vocabulary (FALSIFIED / INCONCLUSIVE / PARKED — **no VALIDATED** exists), trial-slot ledger (6 slots), production boundary, and reopening rules in `RESEARCH_PROGRAM_STATUS.md` are internally consistent, date-stamped, and guarded by `test_program_status_json.py`. ✅
- Volatility taxonomy (15 modules, 48 tests passing, hash-pinned artifacts) correctly classifies itself as *descriptive/diagnostic*; the doc explicitly forbids production citation. ✅
- **Dashboard does not surface research state at all** — no research/falsified/parked visualization exists, so there is no risk of manufactured research confidence in the UI. Acceptable; optional P3 addition under a clearly-labeled "Research (read-only)" surface using `program_status.json`.
- F-10 was the one governance-adjacent item — adjudicated in `DASHBOARD_CONTRACT.md` §6 (production universe authority = production config; research baseline stays frozen; frozen doc untouched). ✅
- Trade-path metrics (MAE/MFE) appear in the dashboard only at *position* level from `position_excursion.json` — operational monitoring usage, consistent with Phase-2 workstreams; no research chart is exposed as a production KPI. ✅

## 6. Strategy Findings

| Strategy | Code | Tests | Research artifact | Validation | Production status | Dashboard |
|---|---|---|---|---|---|---|
| `risk_conditioned_continuation` R4.0 | `scripts/r4_rebalance_loop.py` + manifest | P0/risk/enforcement suites | R4 frozen; R0–R8 closed | Frozen ≠ proven profitable | Phase 2 evidence collection (live, $5K tier) | **Not represented as a strategy entity** — dashboard shows authorization/health/evidence, not strategy ID/version |

No stale strategy names, versions, or performance numbers found in UI or docs. Gap (P3): `/system` build panel shows no `strategy.version`/`manifest_fingerprint` (available from build identity) — would let operators confirm which frozen artifact is live.

## 7. Risk Findings

- Envelope endpoint reads `RiskEnvelope.from_config()` — authoritative, 503 on absence (no fabrication). ✅
- Risk state prefers persisted `risk_state.json` (loop-written only, as of the single-writer fix), falls back to live RiskObserver. ✅
- Risk page dimension groups (`DIMENSION_GROUPS`) match RiskObserver dimension names. ✅
- Utilization bars compute `value/limit` per dimension — ratio-safe across heterogeneous units. ✅
- Units now displayed explicitly per dimension; drawdown gauge percent-scaled with no zero fallback. ✅

## 8. Execution Findings

Signal → Target → Risk decision → Order → Fill → Position is **not reconstructible in the dashboard**: positions come straight from `mt5.positions_get()`, orders/fills from `decisions.jsonl` aggregates, with no correlation into the position detail. The lifecycle strip (F-05) *visually asserted* the chain instead of querying it — removed. Per §12, this chain must be rendered only when per-ticket event correlation is genuinely implemented; the reconciliation page already distinguishes derived-vs-engine state honestly.

## 9. Dashboard Data-Lineage Report

| UI Component | Source | API | Backend owner | Canonical model | Freshness | Tests |
|---|---|---|---|---|---|---|
| Overview auth banner | health dims | `/system/health`, `/health` | `DashboardStateService.get_system_health` | loop/supervisor files | ✅ LIVE/STALE/UNKNOWN | contract tests |
| Overview metrics | MT5 | `/portfolio/account` | `get_account_state` | MT5 account_info | ✅ | DTO tests |
| Gate strip | `/health` dimensions | `/health` | service | files + MT5 probe | ✅ (fixed F-06) | dimension tests |
| HealthMatrix | health dims | `/health` | service | files + MT5 probe | ✅ | dimension tests |
| Positions table | MT5 + excursion file | `/portfolio/positions` | `get_positions` | MT5 + `position_excursion.json` | ✅ | DTO/mae-mfe tests |
| Lifecycle strip | ~~hardcoded~~ | — | — | — | ✅ removed (F-05) | — |
| Risk heatmap/bars/gauge | RiskObserver | `/risk` | `get_risk_state` | observer/json | ✅ (fixed F-14) | DTO tests |
| Risk envelope | config | `/risk/envelope` | `RiskEnvelope.from_config` | config.toml `[live_risk]` | static | 503 path tested |
| Evidence/gates | reports files | `/evidence/qualification` | derive-from-evidence | evidence dir | ✅ | DTO tests |
| Shadow REDUCED | shadow file | `/evidence/shadow-reduced` | service | shadow_reduced.json | ✅ labeled NOT APPLIED LIVE | label test |
| Alerts | alert/monitor logs | `/alerts` | `get_recent_alerts` | jsonl | ✅ (fixed F-03) | ordering regression test |
| Events | decisions ledger | `/evidence/events` | route mapping | decisions.jsonl | ✅ (⚠ F-07 open) | — |
| Build/System | build_pinning | `/system/build`,`/system/info` | `compute_build_identity` | repo state | ✅ | DTO tests |
| LiveConnectionIndicator | **WS `/ws/live`** | ws (authenticated) | streaming/events | shared cached snapshot | ✅ (fixed F-04) | websocket tests + auth tests |

**No hardcoded P&L, fake timestamps, static percentages, random/demo data, or mock fixtures found in the frontend** (searched; only input `placeholder` attributes matched). The fabrications present were F-05/F-06 and the zero-fallback in F-14 — all fixed.

## 10. Dashboard UX Audit

- **IA**: Overview (state) → Positions/Risk/Recon/Alerts → Evidence/Events → System matches the operator questions in §15 well. Missing: a Data page (freshness/quality/universe) — currently only inferable from Risk `stale_data` dimension. (P3)
- **Above the fold**: authorization banner + health matrix + 6 core metrics — correct priority ordering.
- **Truthfulness UI**: `dataState.tsx` + `FreshnessIndicator` implement unknown ≠ zero, stale suffix, relative time. Gate strip now unknown-safe. Some pages still render `"No data"` strings ad hoc (P3 consolidation).
- **Tables**: sortable, filterable, sticky-header, row expansion — first-class. Minor: duplicate sort keys (`holding_time` reused for SL/Risk columns) — P3.
- **Alerts page**: severity panels match §21 taxonomy (informational/warning/critical); no ack workflow (P3).
- **Responsive**: dedicated mobile nav, card lists, compact stats — solid. **Accessibility**: skip-link, sr-only chart summaries, focus-visible, reduced-motion all present; concerns: 9–10px font sizes and `#52525b` muted text near contrast floor (P3).
- **Performance**: react-query intervals 5–60s are moderate; risks: full-file JSONL scans on every alerts/events read (unbounded growth, P3), `get_recent_events(limit=1000)` parsed per request. WS scaling fixed (shared broadcaster).

## 11. Premium Design Audit

`index.css` defines a real design system: 6-step surface scale, border/text hierarchies, semantic palette with subtle variants, 4px spacing scale, restrained radii, tabular-nums via `.ec-num`/mono, panel/badge/table primitives, shimmer/pulse/flash motion with `prefers-reduced-motion` support, tooltip primitive. Deuteranopia-safe chart palette in `RiskCharts.tsx` with 60/80% threshold rails. This is a **serious quant-terminal aesthetic — not crypto-bro**: dark, dense, calm, semantic color.

Gaps: numeric formatting is only partially centralized (`formatCurrency/formatPercent/formatNumber` exist but pages mix inline `.toFixed(2)`/`(x*100).toFixed(2)` — inconsistent precision); status-color mapping exists in **four** places (`utils.getStateColor/getStateBg`, `RiskCharts.getLevelColor`, `StatusDot` levels, `Risk.tsx getLevel`) — should collapse to one token mapping (P2); no light theme (acceptable — terminals are dark).

## 12. Dashboard Redesign Recommendation

**B — Refine** (evidence-based, per §30):

- **Keep**: read-only service/DTO/route architecture; freshness model; contract + security tests; token system; page IA; table/chart primitives.
- **Refine**: remove fabrications (done: F-05, F-06); fix ordering/units/labels (done: F-03, F-14, F-09, F-16); centralize formatting + status-color mapping; single-writer rule (done: F-11/F-12); remaining P2 items (F-07, F-08, F-13) and P3 polish.
- **Not warranted**: re-architecture/redesign — no structural data-lineage rot; every important metric has identifiable lineage.

## 13. Prioritized Fix List

**P0 — correctness/safety**: none found (read-only boundary, auth on REST, fail-closed semantics all verified).

**P1** — all resolved 2026-09-25:
1. ✅ Fix `get_recent_alerts` ordering (F-03).
2. ✅ Authenticate `/ws/live` (token query/subprotocol) + single shared broadcaster loop (F-04).
3. ✅ Remove lifecycle fabrication (F-05).
4. ✅ Fix drawdown gauge units + no-data state; add unit suffixes to risk rows (F-14).
5. ✅ Rewrite `DASHBOARD_DATA_TRUTH_MATRIX.md` against current code (F-01).
6. ✅ Adjudicate USOIL baseline-vs-production (F-10) — frozen research doc untouched.

**P2**
7. Replace gate-strip proxies with real dimension checks from `/health` (F-06) — ✅ done in P1 pass.
8. Swap `newest/oldest_timestamp` in events route (F-07) — ✅; handle `SUFFICIENT/COLLECTING` gate states in Evidence page (F-08) — ✅; relabel Closed Trades → `completed_lifecycles` (F-09) — ✅.
9. Dashboard stops writing `risk_state.json` (F-11) — ✅; move fallback risk constants to observer defaults (F-12) — ✅; drop DTO 250 default (F-13) — ✅.
10. Correct per-metric freshness timestamps on Overview (F-16) — ✅; collapse status-color maps to one module — ✅ (`lib/status.ts` created; `utils.ts`, `RiskCharts.tsx`, `Risk.tsx` routed through it); complete `DASHBOARD_API.md` (F-02) — ✅.
11. Frontend: document prod injection of `VITE_API_KEY` — ✅ (`.env.example` expanded + contract §8.4).

**P3** — remaining: Data page (data freshness/quality; IA change deferred); strategy identity on System page; alerts acknowledge workflow; events virtualized table; JSONL read windows; a11y font sizes (9–11px) deferred to design-system consolidation. Resolved 2026-09-25: alert-count label fix ("showing N of M"); status-color/`formatDimName` consolidation (via `lib/status.ts` single module); health `"NORMAL"` vocabulary bleed (F-15).
Resolved 2026-09-25 (inventory pass, §18): a11y contrast pass (muted `#52525b`→`#8b8b95` = 5.9:1), StatusBadge/StatusDot aria-label corrections, keyboard-reachable position rows, single `h1` per route, 44px mobile filter targets, `role="alert"` critical panel, per-route `document.title`, static page-title/gear-dup dead-CSS cleanup, fonts actually loaded (`@fontsource-variable`, bundled), raw `toFixed` outside `lib/utils.ts` eliminated (0 remaining), Overview "Exposure"→"Margin Used" + shadow row demoted to sourced-policy footnote.

## 14. Exact Files Changed (Phase 2, P1 pass — 2026-09-25)

```text
src/eigencapital/dashboard/services/dashboard_state.py
  change: alerts [:limit] after desc sort (F-03); removed _persist_json/_append_jsonl/_ensure_dirs
          (single-writer, F-11); RiskObserver defaults instead of hardcoded 0.30/0.80 (F-12)
  tests:  tests/unit/dashboard/test_p1_sync_fixes.py (ordering, no-persist, no-duplicated-constants)
src/eigencapital/dashboard/streaming/events.py
  change: authenticated /ws/live (token/Bearer, 1008 close); one shared broadcaster task;
          cached state snapshot (≤5s); per-connection poll loops removed (F-04)
  tests:  TestWebSocketAuth, TestSharedBroadcaster
dashboard/src/lib/config.ts
  change: getWsUrl() appends ?token=<VITE_API_KEY|dev fallback>
dashboard/src/pages/Positions.tsx
  change: removed hardcoded lifecycle strip (desktop + mobile) per contract T1
dashboard/src/pages/Overview.tsx
  change: gate strip reads actual /health dimensions with unknown-safe rendering (F-06);
          per-metric freshness timestamps (F-16); Completed Lifecycles label (F-09)
dashboard/src/pages/Risk.tsx
  change: formatObsValue unit map (pct/usd/count); drawdown gauge percent-scaled with
          explicit no-data state, zero-fallback removed (F-14)
docs/production/DASHBOARD_DATA_TRUTH_MATRIX.md
  change: regenerated (F-01) — resolved sections, single-writer notes, auth/transport notes
docs/production/DASHBOARD_CONTRACT.md
  change: NEW governing contract (truthfulness T1–T5, lineage, single-writer, research
          boundary, USOIL adjudication §6, master-prompt addendum §7)
docs/DOCUMENTATION_SOURCE_OF_TRUTH.md
  change: registered contract + matrix + USOIL adjudication as authoritative pointers
tests/unit/dashboard/test_p1_sync_fixes.py
  change: NEW — 15 regression tests covering F-03, F-11, F-12, F-04
```

## 15. Implementation Plan (small, independent commits)

1. `fix(dashboard): alert ordering + no risk-state writes` (+tests) — **done**
2. `fix(dashboard-api): authenticate /ws/live, single broadcaster` (+tests) — **done**
3. `fix(ui): remove lifecycle fabrication; truthful gate strip` — **done**
4. `fix(ui): risk units, drawdown no-data state, per-metric freshness` — **done**
5. `fix(api): events newest/oldest; evidence gate states in UI` — **done**
6. `docs: regenerate DASHBOARD_DATA_TRUTH_MATRIX + DASHBOARD_CONTRACT` — **done**
7. `refactor(ui): centralize formatting + status-color tokens` — **done** (`lib/status.ts`)
8. `docs: USOIL universe adjudication note` — **done**

## 16. Verification Plan

- ✅ `python -m pytest tests/unit/dashboard -q` — 115 passed (97 baseline + 15 F-fix tests + 3 e0-nesting tests)
- ✅ `python -m mypy src/eigencapital/dashboard` — clean
- ✅ `python -m ruff check src/eigencapital/dashboard tests/unit/dashboard` — clean; full `ruff check src/eigencapital/ scripts/` — clean
- ✅ `cd dashboard && npx tsc -b` — clean · `npx oxlint src` — 0 warnings
- ✅ `npx vite build` — clean
- ✅ `python -m pytest tests/unit/live -q` — 345 passed (guard: no trading behavior change)
- ✅ Playwright pass over 8 routes × desktop/tablet/mobile with live API — 24/24 combos: zero horizontal overflow, exactly one `h1` per route, per-route `<title>`, zero console errors; DOM probe confirms both WS indicators connect (`/ws/live?token=…` → 101 + state stream), `Inter Variable`/`JetBrains Mono Variable` loaded
- ✅ Full final battery: `tests/unit` — 3349 passed / 2 skipped · `tests/integration tests/property src/eigencapital/dashboard/tests` — 51 passed · `tests/failure_injection tests/simulation` — green · `detect.mjs --json dashboard/src` — `[]`

## 17. Final Consistency Checklist

- [x] Documentation matches implementation — truth matrix + API doc regenerated/completed
- [x] README matches implementation (status table verified against PHASE_STATUS + config)
- [x] Research status matches canonical registry (doc + guarded JSON)
- [x] Strategy status matches research governance (frozen ≠ proven, stated)
- [x] Asset universe synchronized (USOIL adjudicated, contract §6)
- [x] Risk definitions synchronized (single `[live_risk]` authority)
- [x] Execution state synchronized — lifecycle conflation removed
- [x] API contracts match frontend (typed client; gate-vocabulary alignment fixed F-08)
- [x] Dashboard metrics have authoritative sources (lineage matrix §9)
- [x] No fabricated production data — lifecycle strip removed; gate strip truthful
- [x] Stale states are explicit (dataState + FreshnessIndicator; consolidation P3)
- [x] Unknown ≠ zero — drawdown zero-fallback removed
- [x] Live ≠ paper — execution_mode surfaced; demo label in config (P3 nicety)
- [x] Research ≠ production (no research surface; taxonomy doc boundary explicit; contract §5)
- [ ] Signal ≠ target ≠ order ≠ fill ≠ position distinguishable in UI — strip removed; true correlation requires backend work (documented)
- [x] Dashboard calculations do not duplicate backend logic (unit map is presentation-only)
- [x] Responsive behavior acceptable
- [x] Accessibility acceptable (foundations; P3 polish items)
- [x] Performance acceptable (WS scaling fixed; JSONL scans flagged P3)
- [x] Security boundaries preserved (REST auth/rate-limit/CORS/GET-only, .env ignored; **WS now authenticated**)
- [x] Tests pass (112 dashboard; volatility 48; mypy/ruff/tsc/oxlint/vite build clean)
- [x] Build passes
- [x] Playwright: not run (no live API session); planned in §16
- [x] Documentation updated
- [x] No research governance rules bypassed (frozen research doc untouched; no new experiments)

## 18. Inventory-Driven Pass (2026-09-25, batches 1–8)

Second sweep: every review-comment source (this register, contract §8, DASHBOARD_API/SECURITY docs, impeccable critique minors, code TODO/FIXME, debt registers, gap/roadmap docs) re-scanned and processed in verified batches.

1. **Backend correctness (batch 1):** `routes/evidence.py` qualification counts read nested `evidence_maturity` (`_count()`); `TestQualificationMaturityNesting` added — `tests/unit/dashboard` 112→115.
2. **Frontend truthfulness (batch 2):** phantom `CommandPalette` mount removed (`Layout.tsx:74`); System "Guarantees" 3-state sourced from `/health` dimensions; Reconciliation duplicate "Reconciled" column removed; Evidence gate bar de-faked (full-width status rule, no 50% meter).
3. **Freshness + errors (batch 3):** server freshness level = single authority (`FreshnessIndicator` rewrite + `formatDateTime` NaN guards); `PageError` wired into all 8 routes; dated alert/event timestamps; TRADE severity + "showing N" label.
4. **Security truth (batch 4):** DEV-gated key fallback in `api.ts`/`config.ts` (prod fails closed); `secrets.compare_digest` for token/Bearer compare; `DASHBOARD_SECURITY.md` rewritten to the implemented model.
5. **Docs (batch 5):** `DASHBOARD_API.md` F-02 completed (Alerts/Reconciliation/SSE sections; real dimension names; version authority pyproject 0.5.0); CHANGELOG `[Unreleased]`; README quick-start; DOCUMENTATION_SOURCE_OF_TRUTH +3 rows.
6. **Dead code + hygiene (batch 6):** removed `MetricCard.tsx`, `api/dependencies.py`, `tests/unit/strategies`, `prop/` orphan dirs, `.focus-visible-ring` + `[data-ec-tooltip]` CSS; `dataState.tsx` trimmed to `getFreshnessInfo`; `formatDimName` centralized in `lib/utils.ts`; CONFIGURATION_INVENTORY RiskPolicy rows corrected; freebuff-added `DATA_SOURCES` constant accommodated (read-only contract test now inspects callables only) + missing `import os` fixed in `dashboard_state.py`.
7. **A11y + critique minors (batch 7):** muted contrast `#52525b`→`#8b8b95` (5.9:1); StatusBadge variant aria-label removed (badge announces visible text); StatusDot `role="img"` color-alternative; positions rows keyboard-reachable (Enter/Space); single `h1` (brand demoted to span); 44px mobile filter/search targets; critical alerts `role="alert"`; per-route `document.title`; More-gear→ellipsis icon; sidebar READ-ONLY green dot removed; Overview "Exposure"→"Margin Used" + shadow row → policy footnote; raw `toFixed` outside `lib/utils.ts` → 0; fonts bundled via `@fontsource-variable/*` (were declared-but-never-loaded; Vite restarted to drop stale root-`node_modules` resolution).
8. **CI/tests (batch 8):** `hypothesis>=6.0` added to `dev` extra (property suite imports it); `ci.yml` gained property/integration/failure-injection/simulation/dashboard suites (gated to py3.13) + `frontend` job (npm ci, oxlint, tsc+build).

Flagged (not changed — outside read-only/review scope): risk-config authority split (`[risk]` dead / bare `RiskPolicy()` defaults), `execution_mode="live"` hardcoded in `/health/authorization`, alert acknowledge workflow (needs POST), `consecutive_count` backend gap, enum duplication, Data-page IA, events virtualization/JSONL windows, 9–11px font sizes (design-system consolidation), chart-palette-vs-token hex divergence (intentional deuteranopia-safe palette, documented), staleTime-5s-vs-LIVE labeling (server freshness thresholds decide).

---

*Governing principle honored: the dashboard is a window into EigenCapital, not a second EigenCapital. All P1 findings and all P2 audit findings are resolved and verified (F-01 through F-16; the only remaining items are the P3 enhancements listed in §13, which are feature additions rather than defects).*
