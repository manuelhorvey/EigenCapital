# QuantForge Dashboard — Architecture v1.0

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

**Structural sharing contract:** React Query's built-in `structuralSharing` preserves sub-object references across polls when the server payload hasn't changed. The `select` function returns these stable references → `memo` guards work correctly.

### 3. UI Domain Layer

**Routes (HashRouter):**

| Route | Component | Data slices |
|-------|-----------|-------------|
| `/dashboard` | `DashboardOverview` | portfolio, snapshot, health |
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
                ├── Header (memo)
                │   ├── EngineDot → useEngineHealth()
                │   ├── QuickStatsBar (memo) → useSystemSnapshot(portfolio)
                │   └── SystemHealthModal button
                ├── SystemDegradedBanner
                ├── Sidebar (memo) → useEngineHealth only
                ├── TabBar
                └── <Routes>
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
| `Header` | Yes | `onMenuClick` (stable) | route change, snapshot tick |
| `QuickStatsBar` | Yes | none | portfolio slice change |
| `EngineBadge` | Yes | none | engine health tick |
| `NavItem` | Yes | `item` (const), `onClose` (stable), `onKeyDown` (stable) | route change only |
| `Sidebar` | Yes | `open`, `onClose` (stable) | sidebar toggle, route change |
| `DashboardOverview` | Yes | none | snapshot slice change |
| `QuickStatsGrid` | Yes | none | portfolio slice change |
| `PortfolioSnapshotPanel` | Yes | none | snapshot slice change |
| `RiskSignalPanel` | Yes | none | snapshot slice change |
| `SignalsTable` | Yes | none | snapshot slice change + search input |
| `TradeFeed` | Yes | none | trades + engine status slice change |

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
| `lib/queryKeys.ts` | QUERY_KEYS contract (4 keys) |
| `types/bundle.ts` | SystemBundle type definition |
| `utils/motion.ts` | Motion tokens + className presets |
| `components/layout/AppShell.tsx` | Integrity layer + persistent layout |
| `components/layout/Sidebar.tsx` | Navigation shell (3 regions) |
| `components/layout/TabBar.tsx` | Route tab bar (NavLink) |
| `components/Header.tsx` | App header (5 sub-components, memoed) |
| `components/SystemHealthModal.tsx` | Engine monitoring modal |
| `pages/DashboardOverview.tsx` | Dashboard (3 memo blocks) |
| `components/layout/MobileLayout.tsx` | *(deleted — dead code)* |
