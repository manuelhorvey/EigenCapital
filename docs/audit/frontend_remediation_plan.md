# Frontend Audit — Remediation Commit Plan

**Branch strategy:** One branch per phase. Each phase is independently reviewable and merges without breaking the others.

**Branch naming:** `fix/frontend-<phase-letter>-<short-desc>`

**Commit convention:** `fix(frontend)` or `feat(frontend)` or `test(frontend)` as appropriate.

---

## Phase A — Foundation (2–3 commits)

**Branch:** `fix/frontend-a-tsconfig-and-dead-code`

### Commit A1: `fix(frontend): enable strict tsconfig, fix violations`

| Scope | Changes |
|-------|---------|
| `paper_trading/dashboard/tsconfig.json` | Set `noUnusedLocals: true`, `noUnusedParameters: true` |
| Various `.ts/.tsx` files | Fix all unused variable/parameter violations |

**Risk:** Low — TS compiler catches these. Run `tsc -b` after to verify.

### Commit A2: `fix(frontend): remove duplicate EquityCurveSparkline`

| Scope | Changes |
|-------|---------|
| File system | Delete one of the two identical `EquityCurveSparkline.tsx` files |
| Any import that referenced the deleted copy | Update to canonical path |

**Risk:** Very low — both files are identical.

### Commit A3: `fix(frontend): remove unused Panel hoverable prop, fix doc-drift`

| Scope | Changes |
|-------|---------|
| `src/components/ui/Panel.tsx` | Remove `hoverable` prop from interface and implementation |
| `docs/ARCHITECTURE.md` | Remove reference to non-existent `selectors/metrics.ts` |
| `docs/audit/frontend_audit_2026-07-08.md` | (already correct — no action needed) |

**Risk:** Very low — prop was never used by any consumer.

---

## Phase B — Performance (3–4 commits)

**Branch:** `fix/frontend-b-render-performance`

### Commit B1: `fix(frontend): add per-asset selector to AssetCard to prevent 22x re-render`

| Scope | Changes |
|-------|---------|
| `src/hooks/useSystemSnapshot.ts` or new file | Add `createAssetSelector(name)` factory that returns a selector for a single asset slot |
| `src/selectors/system.ts` | Add `systemSelectors.asset(name)` |
| `src/components/AssetCard.tsx` | Replace `systemSelectors.snapshot` with per-asset selector |

**Why:** Currently every `AssetCard` reads the full snapshot. When any asset updates, all 22 cards re-memoize. A per-asset selector means only the affected card re-renders.

**Risk:** Low — well-understood pattern, tested via existing tests.

### Commit B2: `fix(frontend): add slice selectors to useMonitorAlerts and useGovernanceRadar`

| Scope | Changes |
|-------|---------|
| `src/hooks/useMonitorAlerts.ts` | Call `useSystemSnapshot(systemSelectors.snapshot)` instead of `useSystemSnapshot()` |
| `src/hooks/useGovernanceRadar.ts` | Same fix |
| `src/selectors/system.ts` | Add any additional selectors needed (e.g., `haltConditions`) |

**Why:** These hooks currently read the full bundle, causing unnecessary re-renders on every 5s poll. ARCHITECTURE.md § "Key Contracts" explicitly forbids this except for AppShell and internal derivation hooks.

**Risk:** Low.

### Commit B3: `fix(frontend): increase EquityChart MAX_POINTS to 2000`

| Scope | Changes |
|-------|---------|
| `src/components/EquityChart.tsx` | Change `MAX_POINTS = 200` → `MAX_POINTS = 2000` |

**Why:** 200 points at 5s intervals = 17 minutes. 2000 points = ~2.8 hours, still well under the browser rendering budget for an SVG line chart.

**Risk:** Very low — one constant change.

### Commit B4 (optional): `refactor(frontend): standardize Zod error handling to safeParse`

| Scope | Changes |
|-------|---------|
| `src/hooks/useEngineHealth.ts` | Replace `.parse()` with `.safeParse()` + console.error |
| `src/hooks/useWalTimeline.ts` | Same |
| `src/hooks/useAssetDeepDive.ts` | Same |
| `src/hooks/useTrades.ts` | (already uses safeParse — keep) |

**Why:** Inconsistent error handling means some endpoints crash on schema drift while others degrade gracefully. Standardizing to `.safeParse()` everywhere prevents full crashes.

**Risk:** Low — behavioral change is graceful degradation instead of error state.

---

## Phase C — Testing (2–3 commits)

**Branch:** `test/frontend-c-integration-tests`

### Commit C1: `test(frontend): add integration test for systemSnapshot data flow`

| Scope | Changes |
|-------|---------|
| `src/hooks/__tests__/useSystemSnapshot.test.tsx` | Expand to test: fetch → parse → select → render path |
| New test file: `src/components/__tests__/SystemHealthSummary.integration.test.tsx` | Test SHS with mocked bundle data renders correctly |

**Add Test Utility:** Mock the `/state-bundle.json` endpoint with a realistic bundle fixture.

### Commit C2: `test(frontend): add error state tests for top 10 components`

| Scope | Test files for: |
|-------|-----------------|
| `TradeFeed` | Error + empty states |
| `SignalsTable` | Empty + search-filtered-empty |
| `EquityChart` | Empty + loading |
| `ExecutionFeed` | Empty + all-blocked states |
| `HaltConditions` | All-passing + some-failing states |
| `AssetMiniGrid` | No-open-positions |
| `PekScalarPanel` | Missing PEK data (empty state) |
| `AdmissionPanel` | Missing data |
| `HealthMonitorPanel` | Error response + empty |
| `WeeklyReviewModal` | No-trades + normal |

### Commit C3: `test(frontend): add Playwright smoke test (new dev dependency)`

| Scope | Changes |
|-------|---------|
| `package.json` | Add `@playwright/test` dev dependency |
| New: `e2e/` directory | Basic smoke test: navigate to all 4 routes, verify key elements render |
| `.github/workflows/` or CI config | Add Playwright run to CI |

---

## Phase D — Accessibility (2 commits)

**Branch:** `fix/frontend-d-accessibility`

### Commit D1: `fix(frontend): add skip-to-content link, fix color-only indicators`

| Scope | Changes |
|-------|---------|
| `src/components/layout/AppShell.tsx` | Add skip-to-content link (`<a href="#main-content">`) as first focusable element |
| `src/components/layout/AppShell.tsx` | Add `id="main-content"` to `<main>` |
| `src/components/SignalsTable.tsx` | Add `aria-label` text alongside `DirectionGlyph` color indicators |
| `src/index.css` | Style skip-link: visually hidden until focused |

### Commit D2: `feat(frontend): add Content Security Policy header`

| Scope | Changes |
|-------|---------|
| `paper_trading/dashboard/index.html` | Add `<meta http-equiv="Content-Security-Policy">` tag |
| Policy includes: `default-src 'self'`, `style-src 'self' fonts.googleapis.com`, `font-src fonts.gstatic.com`, `img-src 'self' data:`, `script-src 'self'` |

---

## Phase E — UX Polish (3 commits)

**Branch:** `fix/frontend-e-ux-polish`

### Commit E1: `fix(frontend): implement formal modal stack (FAILURE_MODE F9)`

| Scope | Changes |
|-------|---------|
| New: `src/hooks/useModalStack.ts` | Generic modal stack hook with `push`, `pop`, `top` |
| `src/App.tsx` | Replace independent `detailAsset`/`deepDiveAsset` booleans with modal stack |
| `src/hooks/useSystemHealthModal.tsx` | Integrate with modal stack |
| `src/components/WeeklyReviewModal.tsx` | Integrate with modal stack |

**Why:** Currently, `AssetDetailPanel` and `AssetDeepDive` use independent state with a comment in `App.tsx` acknowledging the stacking problem. A formal modal stack prevents z-index conflicts, escape-key desyncs, and stale backdrop issues.

### Commit E2: `fix(frontend): add fast-path endpoint for recent fills (FAILURE_MODE F12)`

**Backend change:**
| Scope | Changes |
|-------|---------|
| `paper_trading/serve.py` or `paper_trading/api/handler.py` | Add `/recent-fills.json` endpoint returning last 20 fills (no cache) |
| Engine loop | Write `recent_fills.json` each cycle (last 20 fills) |

**Frontend change:**
| Scope | Changes |
|-------|---------|
| `src/components/TradeFeed.tsx` | Add 2s poll to `/recent-fills.json` for recent trades |
| Keep existing `/trades.json` for paginated history |

### Commit E3: `refactor(frontend): migrate all hooks to createApiQuery factory`

| Scope | Changes |
|-------|---------|
| `src/hooks/useTrades.ts` | Rewrite using `createApiQuery` |
| `src/hooks/useWeeklyReview.ts` | Same |
| `src/hooks/useWalTimeline.ts` | Same |
| `src/hooks/useAssetDeepDive.ts` | Same |
| `src/hooks/useAttributionTrades.ts` | Same |

**Why:** Two patterns exist for the same thing. The factory is more concise and enforces consistent Zod handling.

---

## Phase F — Polish & Security (2 commits)

**Branch:** `fix/frontend-f-polish-security`

### Commit F1: `fix(frontend): route-level chunk preloading + SignalsTable search optimization`

| Scope | Changes |
|-------|---------|
| `src/App.tsx` | Add `<link rel="modulepreload">` for all 4 lazy routes after initial render |
| `src/components/SignalsTable.tsx` | Use `useDeferredValue` for search input |
| `src/components/QuickStatsGrid.tsx` | Add explicit error state |

### Commit F2: `fix(frontend): secure error reporting endpoint, add CSP`

| Scope | Changes |
|-------|---------|
| `src/components/ErrorBoundary.tsx` | Add auth headers to `/api/log-error` POST |
| Backend `/api/log-error` | Add auth check if not present |
| `src/App.tsx` or `src/index.css` | Final CSP additions |

---

## Execution Order

```
Week 1              Week 2              Week 3
┌─────────┐    ┌──────────┐    ┌────────────┐
│ Phase A │    │ Phase B  │    │ Phase C    │
│ (found.) │    │ (perf)   │    │ (testing)  │
└────┬────┘    └────┬─────┘    └─────┬──────┘
     │               │               │
     ▼               ▼               ▼
┌─────────┐    ┌──────────┐    ┌────────────┐
│ Phase D │    │ Phase E  │    │ Phase F    │
│ (a11y)  │    │ (UX)     │    │ (polish)   │
└─────────┘    └──────────┘    └────────────┘
```

Phases A–D are independent of each other and can be worked on in parallel. Phase E depends on D (modal stack touches App.tsx which also needs a11y changes). Phase F can start any time.

---

## Merge Strategy

Each phase branch is a short-lived branch (< 3 days) that:
1. Branches from `main`
2. Is reviewed in a single PR
3. Merges back to `main` via squash-merge

This keeps each PR focused, reviewable, and low-risk.
