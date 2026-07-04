# EigenCapital Dashboard — Architecture v1.0

## System Boundary

A React SPA (Vite + Tailwind + React Router) serving as a real-time monitoring interface for a cross-asset paper trading engine. Data flows unidirectionally from a single backend state-bundle endpoint through a sliced React Query layer to memoized UI components.

---

## Data Flow

```
Backend (/state-bundle.json)
    │
    ▼ 5s poll (market open) / 30s poll (market closed)
useSystemSnapshot(select?)
    │
    │ React Query structural sharing + keepPreviousData
    ▼
systemSelectors (typed slice functions)
    │
    │ reference equality === data unchanged → no re-render
    ▼
memo(Component) ← slice-only props
```

**Rule:** Only `AppShell` and internal derivation hooks (`useMonitorAlerts`, `useGovernanceRadar`) may read the full bundle. All other components must use `useSystemSnapshot(selector)` with a `systemSelectors` slice.

---

## Three-Layer Architecture

### 1. Integrity Layer (AppShell)

| Responsibility | Implementation |
|---------------|---------------|
| Engine restart detection | `useSnapshotReconciler` — injects `snapshot_sequence_id` into query cache on restart |
| Render gate | `useSystemIntegrity` — computes `shouldBlockRender` from bundle meta `status` |
| Degraded banner | `SystemDegradedBanner` — shown when `isDegraded` is true, below Header |

### 2. Reactive Data Layer

**4 query keys (no more, no fewer):**

| Key | Hook | Endpoint | Poll | staleTime | Select |
|-----|------|----------|------|-----------|--------|
| `['systemSnapshot']` | `useSystemSnapshot(select?)` | `/state-bundle.json` | 5s/30s | 3s | `systemSelectors.*` |
| `['attributionBundle']` | `useAttributionBundle()` | `/attribution-bundle.json` | 30s | 15s | none |
| `['equityHistory']` | `useEquityHistory()` | `/equity-history.json` | 60s | 50s | none |
| `['engineHealth']` | `useEngineHealth()` | `/health` | 5s | 0s | none |

**Selectors:**

```ts
systemSelectors = {
  snapshot:    (b) => b.snapshot,           // EngineSnapshot
  assets:     (b) => b.snapshot.assets,     // Record<string, AssetState>
  portfolio:  (b) => b.snapshot.portfolio,  // PortfolioSummary
  engineStatus: (b) => b.snapshot.engine_status,
  health:     (b) => b.live.health,         // HealthResponse
  mt5:        (b) => b.live.mt5,            // MT5Status
}
```

### State Bundle Fields (Portfolio)

The `portfolio` object in the state bundle includes these additional fields beyond the core `Portfolio` type:

| Field | Shape | Source |
|-------|-------|--------|
| `portfolio_drawdown` | `number` — current portfolio drawdown % | `engine_state_service` |
| `portfolio_peak_value` | `number \| null` — all-time peak portfolio value | `engine_state_service` |
| `position_concentration` | `{ long, short, total, skew, dominant_side, threshold, alert }` — net-short skew | orchestrator Phase 3e |
| `factor_exposures` | `{ exposures, violations, n_violations, within_limits }` — 9-factor limit check | `shared.factor_model.summary()` |
| `live_sharpe` | `{ available, cycle_level, daily_level, portfolio, slippage }` — live Sharpe tracker | `LiveSharpeTracker.compute()` |
| `admission` | `{ n_intents, n_admitted, n_rejected, budget_notional, admitted[], rejected[] }` | PEK Phase 1b |

### EngineSnapshot Top-Level Fields

Beyond `portfolio`, the `EngineSnapshot` includes these top-level fields:

| Field | Shape | Source |
|-------|-------|--------|
| `risk_signals` | `Record<string, RiskSignal> \| null` | per-asset risk signal |
| `shadow_actions` | `Record<string, ShadowAction> \| null` | per-asset shadow governance |
| `emergency_halt` | `boolean` — circuit breaker triggered | orchestrator Phase 3 |
| `halt_reason` | `string` — breaker reason enum | orchestrator Phase 3 |
| `halt_detail` | `string` — verbose breaker reason | orchestrator Phase 3 |
| `peak_portfolio_value` | `number \| null` — all-time peak (orchestrator) | orchestrator |
| `breaker_daily_pnl` | `number[] \| null` — daily P&L list from breaker | `CircuitBreaker.snapshot_state()` |
| `risk_parity` | `dict \| null` — risk parity weights snapshot | `engine_state_service` |

**Structural sharing contract:** React Query's built-in `structuralSharing` preserves sub-object references across polls when the server payload hasn't changed. The `select` function returns these stable references → `memo` guards work correctly.

### 3. UI Domain Layer

**Routes (HashRouter):**

| Route | Component | Data slices |
|-------|-----------|-------------|
| `/` | `CommandCenter` | portfolio, snapshot, health |
| `/trading` | `TradingWorkspace` | snapshot, equity history |
| `/execution` | `ExecutionWorkspace` | snapshot, trades |
| `/risk` | `RiskWorkspace` | snapshot |

**Persistent layout:**

```
ErrorBoundary
└── HashRouter
    └── SelectedAssetProvider (?asset=X)
        └── SystemHealthModalProvider
            └── AppShell
                ├── TickerRail (engine pulse bar with refresh + menu)
                ├── SystemDegradedBanner (integrity)
                ├── EmergencyHaltBanner
                ├── <div flex>
                │   ├── Sidebar (sticky, off-canvas on mobile)
                │   └── <div flex-col>
                │       ├── TabBar (4 NavLink tabs)
                │       └── <main> ← Routes
                └── (modals rendered outside AppShell in AppContent)
                    ├── AssetDetailPanel (conditional)
                    ├── AssetDeepDive (conditional)
                    ├── SystemHealthModal
                    └── WeeklyReviewModal
```

**Modals (always mounted, visibility-controlled):**

| Modal | Data slices | Re-renders when closed? |
|-------|-------------|------------------------|
| `SystemHealthModal` | snapshot + health | No — sliced selectors stable |
| `WeeklyReviewModal` | dedicated `useWeeklyReview` | No — separate query key |
| `AssetDetailPanel` | selected asset from snapshot | Conditional mount |
| `AssetDeepDive` | selected asset from snapshot | Conditional mount |

---

## Memoization Map

| Component | memo? | Key props | Re-render triggers |
|-----------|-------|-----------|-------------------|
| `TickerRail` | Yes (post-Commit-2.2) | `onToggleSidebar` (stable) | slice change on `systemSelectors.snapshot`/`mt5` or engine-health tick |
| `Sidebar` | Yes | `open`, `onClose` (stable) | sidebar toggle, route change |
| `CommandCenter` | Yes | none | slice change via `useTradingState()` |
| `SignalsTable` | Yes | none | snapshot slice change + search input |
| `TradeFeed` | Yes | none | trades + engine status slice change |
| `EmergencyHaltBanner` | Yes (post-Commit-2.2) | none | `systemSelectors.snapshot` slice change (only when `emergency_halt` flips) |
| `AssetCard` | Yes | name | `systemSelectors.snapshot` slice slot for this asset |

> **Note:** `QuickStatsGrid` is defined inline in `CommandCenter.tsx`,
> not a standalone file yet (Commit 3.1 will extract it). `EngineBadge`,
> `NavItem`, `QuickStatsBar`, and `PortfolioSnapshotPanel` are documented
> in prior architecture but no longer exist as standalone components —
> their functionality has been absorbed into inline definitions or removed.

### Slice selector discipline (Key Contract #1)

| Caller | Selector | Note |
|--------|----------|------|
| `AppShell` (integrity root) | none (full bundle) | Documented exception: integrity layer holds the bundle reference for the reconciler + integrity hook |
| `TickerRail` | `systemSelectors.snapshot`, `systemSelectors.mt5` | Commits 2.1+2.2 |
| `EmergencyHaltBanner` | `systemSelectors.snapshot` | Commit 2.1+2.2 |
| `AssetCard` | `systemSelectors.snapshot` | Commit 2.1 |
| `CommandCenter` (page) | composed via `useTradingState()` | Indirect; trading-state hook is internal-derived |
| `TickerRail` mtm | `systemSelectors.mt5` | 2 selectors — see multiple-hook note below |
| `TradingWorkspace` (page) | none | only reads `isPending`/`isError` for status chrome (Commit 2.1 carve-out) |

**Internal derivation hooks (allowed no-selector):** `useSnapshotReconciler`, `useSystemIntegrity`, `useMonitorAlerts`, `useGovernanceRadar`, `useTradingState` (lib/trading-state/hook.ts:50).

Violations prior to Commits 2.1+2.2: `EmergencyHaltBanner`, `AssetCard`, `RebalancingDashboard` (deleted in 3.3), inline `QuickStatsGrid` in `CommandCenter.tsx`. Now compliant.

---

## Motion System

**Tokens** (`utils/motion.ts`):

| Category | Duration | Easing |
|----------|----------|--------|
| Interaction | 150ms | ease |
| Normal/Hover | 200ms | ease |
| Presence | 300-400ms | ease-out |
| Data viz | 500ms | ease-out |
| Emphasis (sidebar) | 300ms | cubic-bezier(0.34, 1.56, 0.64, 1) |

**Reduced motion:** Global `@media (prefers-reduced-motion: reduce)` rule at `index.css` suppresses all `animation-duration` and `transition-duration` to 0.01ms, covering every component.

**Safe-to-animate:** route transitions, modal open/close, sidebar slide, alert appearance.
**Never-animate:** charts, tables, KPI cards, bundle-driven value transitions.

---

## Cache Coherence

### Engine restart detection (`useSnapshotReconciler`)

```
on new bundle:
  if bundle.meta.snapshot_sequence_id < last_seq_id:
    invalidate all queries → hard reload
  if bundle.meta.snapshot_sequence_id drops to 0:
    invalidate all queries → engine cold start
```

### keepPreviousData

Applied to `useSystemSnapshot` — prevents loading flash between polls. Combined with `select`, the previous data slice reference is preserved until the new slice is confirmed structurally identical.

### No cross-invalidation

Each of the 4 query keys is independent. Bundle updates never invalidate trade/equity/attribution queries.

---

## Key Contracts

1. **No component may import `useSystemSnapshot` without a `select` argument**, except `AppShell` and internal hooks.
2. **`systemSelectors` are pure projections of backend-provided fields** — no re-derived scoring or invented semantics.
3. **Route is the sole authority for navigation AND entity focus** (`?asset=X`, `?deepDive=true`). Route state and bundle state are never coupled.
4. **`Object.freeze(snapshot.assets)`** enforces selector purity at the bundle boundary.
5. **All modal visibility is controlled by internal state or context**, never by route params.

---

## File Map

| File | Role |
|------|------|
| `hooks/useSystemSnapshot.ts` | Core query hook with `select` support |
| `hooks/useSnapshotReconciler.ts` | Engine restart detection |
| `hooks/useSystemIntegrity.ts` | Render gate derivation |
| `hooks/useSelectedAsset.tsx` | URL-backed asset focus provider |
| `hooks/useSystemHealthModal.tsx` | Modal visibility context |
| `selectors/system.ts` | `systemSelectors` slice definitions |
| `selectors/portfolio.ts` | Portfolio summary selector (legacy) |
| `selectors/governance.ts` | Governance state selectors |
| `selectors/health.ts` | Health score selectors |
| `selectors/metrics.ts` | Statistical metrics selectors |
| `lib/queryKeys.ts` | QUERY_KEYS contract (4 keys: systemSnapshot, attributionBundle, equityHistory, engineHealth) |
| `types/bundle.ts` | SystemBundle type definition |
| `utils/motion.ts` | Motion tokens + className presets |
| `components/layout/AppShell.tsx` | Integrity layer + persistent layout |
| `components/layout/Sidebar.tsx` | Navigation shell (3 regions) |
| `components/layout/TabBar.tsx` | Route tab bar (NavLink) |
| `components/layout/TickerRail.tsx` | Engine pulse bar (seq, state, tick, PEK, MT5, halt, assets + refresh + menu) |
| `components/SystemHealthModal.tsx` | Engine monitoring modal |
| `pages/CommandCenter.tsx` | Dashboard glance surface (6 sections: SystemHealthSummary, EdgeHealthAlert, LiveSharpeCard, OptimizerRecommendations, HaltConditions, EquityCurveSparkline, AssetMiniGrid, TradingAssetRow table) |
| `components/OptimizerRecommendations.tsx` | Optimization drift detector panel (queries /optimization.json) |
| `components/layout/MobileLayout.tsx` | *(deleted — dead code)* |
