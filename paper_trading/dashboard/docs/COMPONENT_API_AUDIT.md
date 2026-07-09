# Component API Audit & Standardization Guide

Generated: 2026-07-09
Scope: All 43+ React components in `src/components/` and `src/pages/`

---

## 1. Naming Conventions

### ✅ Standard: `interface ComponentNameProps`

Most components follow this pattern:
```tsx
interface ButtonProps { ... }
interface ModalProps { ... }
interface PanelProps { ... }
```

### ⚠️ Exceptions (use generic `interface Props`):
- `SystemDegradedBanner.tsx:6` — `interface Props`
- `WalTimeline.tsx:6` — `interface Props`
- `AssetDetailPanel.tsx:8` — `interface Props`
- `AssetDetailPanel/DiagnosticsTab.tsx:6` — `interface Props`
- `AssetDetailPanel/GovernanceTab.tsx:6` — `interface Props`
- `AssetDetailPanel/OverviewTab.tsx:6` — `interface Props`
- `AssetDetailPanel/SizingTab.tsx:6` — `interface Props`

**Standardize to**: `{ComponentName}Props`

### ⚠️ Inline types instead of named interfaces:
- `AssetDeepDive.tsx:8` — `{ name: string; onClose: () => void }`
- `MetricsSummary.tsx:17` — inline type
- `MaeMfeScatter.tsx` — inline type for trades
- `FeatureImportanceChart.tsx` — inline type for features
- `AssetDetailPanel/helpers.tsx` — some inline, some named

**Standardize to**: Named `interface` for reuse and documentation.

---

## 2. `className` Prop

### ✅ Standard: `className?: string` with `= ''` default

```tsx
interface PanelProps {
  children: ReactNode
  className?: string  // ✓
}
```

22/25 UI primitives follow this standard.

### ⚠️ `Modal.tsx` — uses `className` without default:
```tsx
className,  // undefined when not passed
// used as: (className ?? '')
```
Should be `className = ''` for consistency.

### ⚠️ Components missing `className` entirely:
- `LoadingScreen` — no className prop
- `PanelFallback` — no className prop
- `SystemDegradedBanner` — no className prop

---

## 3. Boolean Naming

### Inconsistent patterns across the codebase:

| Pattern | Examples |
|---------|----------|
| `isX` | `isPending`, `isError`, `isActive`, `is_open`, `isLoading` |
| `hasX` | `hasMore`, `hasData` |
| `x` (no prefix) | `open`, `loading`, `compact`, `filtered`, `stickyHeader`, `sortable`, `showHeader` |

**Recommended standard**: Use `isX` for states, `hasX` for existence checks, and bare names for behavior flags:
- ✅ `isOpen` (not `open`)
- ✅ `isLoading` (not `loading`)
- ✅ `isCompact` (not `compact`)
- ✅ `isSortable` (not `sortable`)
- ✅ `isSticky` (not `stickyHeader`)
- ✅ `hasMore` (✓ already)
- ✅ `hasData` (✓ already)
- ✅ `showHeader` (OK — imperative verb)
- ✅ `filtered` (OK — past participle)

---

## 4. Size Prop Consistency

Three different size scales exist across UI primitives:

| Component | Sizes | Notes |
|-----------|-------|-------|
| `Button` | `'sm' \| 'md' \| 'lg'` | ✅ Consistent with MUI/Chakra standards |
| `Badge` | `'sm' \| 'md'` | ✅ Subset of Button sizes |
| `Select` | `'sm' \| 'md'` | ✅ Same |
| `Modal` | `'sm' \| 'md' \| 'lg' \| 'xl'` | Different — width tiers, not height |
| `Panel` (padding) | `'md' \| 'lg' \| 'none'` | Different — spacing, not size |
| `StatCard` (variant) | `'default' \| 'compact' \| 'kpi'` | Different — visual variant |

**Standard**: Use `'sm' \| 'md' \| 'lg'` for consistent visual sizing. Use `'default' \| 'compact'` for density variants. Use separate `variant` prop for style variants.

---

## 5. Loading State Patterns

| Component | Loading Prop | Notes |
|-----------|-------------|-------|
| `PageShell` | `isPending: boolean` | React Query convention |
| `StatCard` | `loading?: boolean` | Different naming |
| `ChartContainer` | `isPending?: boolean` | Consistent with PageShell |
| `EquityCurveSparkline` | `isPending` | Internal |
| `SystemHealthSummary` | `isLoading` | From hook |

**Standard**: Use `isPending` for initial data load, `isLoading` for background refetch.

---

## 6. Display Names on Memo'd Components

Many `memo()`-wrapped components lack `displayName`:

```tsx
const Sidebar = memo(SidebarInner)  // React DevTools shows "SidebarInner" or "Anonymous"
```

**Fix**: Set `displayName` explicitly:
```tsx
const Sidebar = memo(SidebarInner)
Sidebar.displayName = 'Sidebar'
```

Components affected:
- `TickerRail` (memo(TickerRailInner))
- `Sidebar` (memo(Sidebar))
- `NavItem` (memo(NavItem))
- `CommandCenter` (memo(CommandCenter))
- `QuickStatsGrid` (memo(QuickStatsGridInner))
- `AssetListPanel` (memo(AssetListPanelInner))
- `ThemeToggle` (memo(ThemeToggleInner))

---

## 7. Error Handling Patterns

| Component | Retry Prop | Handles rendering error? |
|-----------|-----------|------------------------|
| `ErrorBoundary` | N/A (cascading) | ✅ |
| `ErrorScreen` | `onRetry?: () => void` | Full-screen |
| `PanelFallback` | Hardcoded `window.location.reload()` | Inline card |
| `PageShell` | None (shows error panel) | Inline |

**Standard**: `PanelFallback` should accept `onRetry?: () => void` like `ErrorScreen`.

---

## 8. Event Handler Naming

| Pattern | Examples |
|---------|----------|
| `onX` | `onClick`, `onClose`, `onChange`, `onPrev`, `onNext`, `onSelectAsset`, `onRetry`, `onRowClick`, `onSortChange` |
| `handleX` | `handleRefresh`, `handleScroll`, `handleKeyDown` (internal) |

**Standard**: `onX` for public props, `handleX` for internal handlers. ✅ Already well-followed.

---

## 9. Priority Actions

| Priority | Action | Impact |
|----------|--------|--------|
| P0 | Rename generic `interface Props` → `interface {Name}Props` | Dev readability, prevents name collisions |
| P0 | Fix `Modal` className default | Consistency |
| P1 | Add `displayName` to memo'd components | DevTools debugging |
| P1 | `PanelFallback` `onRetry` support | Consistency with ErrorScreen |
| P2 | Add `className` to LoadingScreen, PanelFallback, SystemDegradedBanner | Customizability |
| P3 | Standardize `isLoading` vs `loading` | Future API surface |
| P4 | Standardize size prop naming across UI kit | Future API surface |

---

## 10. Summary

The codebase is **already well-standardized** for an organically grown dashboard. The inconsistencies are minor and don't affect runtime behavior. Priority fixes focus on naming conventions and missing customization hooks rather than functional changes.
