# EigenCapital — Dashboard Architecture

**Last updated:** 2026-07-18

> Frontend architecture for the EigenCapital React SPA. Served by the engine's
> HTTP server on port 5000. State is fetched as JSON from the backend and
> rendered via React Query + sliced selectors.

---

## Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Framework | React 18 | UI components |
| Build | Vite | Development server + production builds |
| Language | TypeScript | Type safety |
| Routing | React Router (HashRouter) | Client-side SPA routing |
| State | React Query | Server-state caching + polling |
| Validation | Zod | API response schema validation |
| Styling | Tailwind CSS | Utility-first styling |
| Charts | Recharts | Equity curves, PnL waterfall |
| Icons | Lucide React | UI icons |

## Route Structure

| Route | Page Component | Primary Job |
|-------|---------------|-------------|
| `/` | `CommandCenter` | Glance surface: status row, equity curve sparkline, open positions grid, sortable asset list |
| `/trading` | `TradingWorkspace` | Operate surface: signal queue, admission/rejected, recent trades, execution feed |
| `/execution` | `ExecutionWorkspace` | Quality surface: equity chart, execution quality KPIs, trade attribution |
| `/risk` | `RiskWorkspace` | Governance surface: PEK telemetry, portfolio risk, governance state, health scores |

All routes are lazy-loaded via `React.lazy()` + dynamic `import()`.

## Component Tree

```
<App>
  <QueryClientProvider>
    <HashRouter>
      <AppShell>                          ← Persistent shell, mounts on every route
        <TopBar />                        ← Status + nav: engine state, tick interval, halt status
        <Sidebar />                       ← Navigation: Dashboard / Trading / Execution / Risk
        <main>
          <Routes>
            <Route path="/" element={<CommandCenter />} />
            <Route path="/trading" element={<TradingWorkspace />} />
            <Route path="/execution" element={<ExecutionWorkspace />} />
            <Route path="/risk" element={<RiskWorkspace />} />
          </Routes>
        </main>
        <EmergencyHaltBanner />           ← Mounted globally in AppShell
      </AppShell>
    </HashRouter>
  </QueryClientProvider>
</App>
```

### AppShell Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `TopBar` | `layout/TopBar.tsx` | Status bar + theme toggle: engine state, sequence ID, halt status, asset count |
| `Sidebar` | `layout/Sidebar.tsx` | Navigation rail with route links and engine status chip |
| `TabBar` | `layout/TabBar.tsx` | Responsive bottom tab navigation (mobile viewports) |
| `EmergencyHaltBanner` | `EmergencyHaltBanner.tsx` | Red banner shown during emergency halt states |
| `AlertFeed` | `monitor/AlertFeed.tsx` | Real-time governance event capture tray |
| `SystemDegradedBanner` | `ui/SystemDegradedBanner.tsx` | Yellow banner when engine is in degraded state |
| `ErrorScreen` | `ui/ErrorScreen.tsx` | Full-screen error display with retry |
| `LoadingScreen` | `ui/LoadingScreen.tsx` | Full-screen loading state on initial load |

### CommandCenter Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `EquityCurveSparkline` | `EquityCurveSparkline.tsx` | 80px SVG equity curve from `/equity_history.json` |
| `EquityCurveSparkline` | `EquityCurveSparkline.tsx` | 80px SVG equity curve from `/equity_history.json` |
| `AssetMiniGrid` | `AssetMiniGrid.tsx` | Compact grid of AssetCards for open positions |
| `AssetListPanel` | `AssetListPanel.tsx` | Sortable full-width asset table with search |
| `QuickStatsGrid` | `QuickStatsGrid.tsx` | Hairline-rule quick-stats dl/div row (terminal-precision) |
| `LiveSharpeCard` | `LiveSharpeCard.tsx` | Live Sharpe ratio display |
| `OptimizerRecommendations` | `OptimizerRecommendations.tsx` | TP/SL drift detector recommendations |
| `HaltConditions` | `HaltConditions.tsx` | Halt condition status summary |
| `SystemHealthSummary` | `SystemHealthSummary.tsx` | Engine health summary with status badges |
| `EdgeHealthAlert` | `EdgeHealthAlert.tsx` | Edge health degradation alert banner |

### TradingWorkspace Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `SignalsTable` | `SignalsTable.tsx` | Live signal queue with confidence, direction, asset |
| `AdmissionPanel` | `AdmissionPanel.tsx` | PEK admission: intents, admitted, rejected counts |
| `RejectedSignalExplorer` | `RejectedSignalExplorer.tsx` | Browse rejected signals with rejection reason |
| `TradeOutcomes` | `TradeOutcomes.tsx` | TP/SL/win rate aggregates |
| `TradeFeed` | `TradeFeed.tsx` | Real-time trade event feed |
| `ExecutionFeed` | `ExecutionFeed.tsx` | Execution decision stream |

### ExecutionWorkspace Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `EquityChart` | `EquityChart.tsx` | Full Recharts area chart with drawdown and per-asset overlays |
| `ExecutionQualityStrip` | `execution/ExecutionQualityStrip.tsx` | EIS and FQI KPI row |
| `AttributionBreakdownCard` | `attribution/AttributionBreakdownCard.tsx` | Domain scores grid + PnL waterfall |
| `PnLWaterfall` | `attribution/PnLWaterfall.tsx` | PnL waterfall decomposition bar chart |
| `MaeMfeScatter` | `attribution/MaeMfeScatter.tsx` | MAE/MFE scatter plot colored by archetype |
| `TradeDetailPanel` | `attribution/TradeDetailPanel.tsx` | Per-trade domain score drill-down with progress bars |
| `FillQualityGauge` | `execution/FillQualityGauge.tsx` | SVG arc gauge for composite FQI |
| `SlippageHistogram` | `execution/SlippageHistogram.tsx` | Entry/exit slippage distribution |
| `TradeExecutionTable` | `execution/TradeExecutionTable.tsx` | Full attribution field table |
| `SystemHealthSummary` | `SystemHealthSummary.tsx` | Engine health summary with status badges |
| `TradeTimeline` | `trades/TradeTimeline.tsx` | Trade event timeline visualization |
| `TradeCounterfactual` | `trades/TradeCounterfactual.tsx` | Counterfactual trade comparison |
| `TradeGovernanceAudit` | `trades/TradeGovernanceAudit.tsx` | Governance audit per trade |

### RiskWorkspace Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `GovernanceRadar` | `governance/GovernanceRadar.tsx` | Per-asset governance summary with halt state |
| `GovernanceStateCards` | `GovernanceStateCards.tsx` | Per-asset halted status, validity state, tooltips |
| `GovernanceRadar` | `governance/GovernanceRadar.tsx` | Per-asset governance summary with halt state |
| `PekScalarPanel` | `PekScalarPanel.tsx` | PEK scalar values (risk budget, velocity) |
| `PerformanceStateVelocityChart` | `PerformanceStateVelocityChart.tsx` | Performance velocity over time |
| `RiskBudgetChart` | `RiskBudgetChart.tsx` | Risk budget allocation chart |
| `PositionConcentrationPanel` | `PositionConcentrationPanel.tsx` | Net-short skew visualization |
| `FactorExposureBreakdown` | `FactorExposureBreakdown.tsx` | 10 factor group exposure bars |
| `HealthScores` | `HealthScores.tsx` | Statistical metrics: PSR, DSR, MinTRL |
| `HealthMonitorPanel` | `monitor/HealthMonitorPanel.tsx` | Health monitoring summary panel |
| `DrawdownChart` | `DrawdownChart.tsx` | Portfolio drawdown visualization |
| `CorrelationHeatmap` | `CorrelationHeatmap.tsx` | Asset correlation heatmap |

### Shared UI Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `Panel` | `ui/Panel.tsx` | Panel container (default / elevated variants) |
| `Section` | `ui/Section.tsx` | Section wrapper with optional header |
| `SectionHeader` | `ui/SectionHeader.tsx` | Section title with static 1px accent dot |
| `StatCard` | `ui/StatCard.tsx` | KPI/metric display card |
| `Badge` | `ui/Badge.tsx` | Status badge (GREEN/YELLOW/RED) |
| `Button` | `ui/Button.tsx` | Styled action button |
| `Select` | `ui/Select.tsx` | Dropdown select |
| `Divider` | `ui/Divider.tsx` | Hairline rule divider |
| `Tooltip` | `ui/Tooltip.tsx` | Hover tooltip |
| `EmptyState` | `ui/EmptyState.tsx` | Empty section placeholder (contextual icon: SearchSlash vs Inbox) |
| `Modal` | `ui/Modal.tsx` | Modal dialog shell (4px corner, shadow-modal) |
| `Skeleton` | `ui/Skeleton.tsx` | Loading skeleton (table / metric card variants) |
| `DataTable` | `ui/DataTable.tsx` | Sortable data table with sticky header |
| `TablePagination` | `ui/TablePagination.tsx` | Table pagination controls |
| `ProgressBar` | `ui/ProgressBar.tsx` | Horizontal progress bar with BarRow extraction |
| `SltpGauge` | `trades/SltpGauge.tsx` | SL/TP hit rate gauge (3 stacked BarRows) |
| `Gauge` | `ui/Gauge.tsx` | SVG arc gauge |
| `ChartContainer` | `ui/ChartContainer.tsx` | Chart wrapper with responsive sizing |
| `EntranceAnimator` | `ui/EntranceAnimator.tsx` | Entrance animation wrapper for sections |
| `PanelFallback` | `ui/PanelFallback.tsx` | Panel-level error fallback (Zod validation errors) |
| `ErrorBoundary` | `ErrorBoundary.tsx` | Component-level error boundary |
| `EmptyState` | `ui/EmptyState.tsx` | Empty state with contextual icon |

### Modals

| Component | Location | Purpose |
|-----------|----------|---------|
| `TradeInspectorModal` | `trades/TradeInspectorModal.tsx` | Full trade inspection with domains, timeline, counterfactual |
| `SystemHealthModal` | `SystemHealthModal.tsx` | Engine health detail modal |
| `WeeklyReviewModal` | `WeeklyReviewModal.tsx` | Weekly performance review modal |
| `AssetDetailPanel` | `AssetDetailPanel.tsx` | Multi-tab asset detail (Overview/Governance/Sizing/Diagnostics) |

### AssetCard Subcomponents

| Component | Location | Purpose |
|-----------|----------|---------|
| `AssetCardCompact` | `asset-card/AssetCardCompact.tsx` | Compact variant for dense grids |
| `AssetCardHeader` | `asset-card/AssetCardHeader.tsx` | Asset header row (name, signal, price) |
| `AssetCardMetrics` | `asset-card/AssetCardMetrics.tsx` | Metric row (return, drawdown, confidence) |
| `AssetCardPosition` | `asset-card/AssetCardPosition.tsx` | Position details (entry, SL, TP, PnL) |

## State Management

### Data Flow

```
Backend (port 5000)                    Frontend (browser)
┌─────────────────────┐               ┌──────────────────────────┐
│ /state-bundle.json   │─────fetch───▶│ React Query              │
│ /state.json          │              │  └─useSystemSnapshot()   │
│ /health.json         │              │     └─sliced selectors   │
│ /governance.json     │              │        per component     │
│ /narrative.json      │              │                          │
│ ...                  │              │  Poll: 5s (open)         │
└─────────────────────┘              │        30s (closed)      │
                                     └──────────────────────────┘
```

### Key Hooks

| Hook | Source Endpoint | Refresh | Purpose |
|------|----------------|---------|---------|
| `useSystemSnapshot()` | `/state.json` | 5s / 30s | Primary state bundle for all components |
| `useEngineHealth()` | `/health` | 30s | Liveness indicator + sequence ID |
| `useAttributionBundle()` | Multiple `/attribution/*` | 30s | Trade attribution data |
| `useTrades()` | `/trades.json` | 30s | Trade history with pagination |
| `useMonitorAlerts()` | Multiple | 30s | Governance alert feed |
| `useSidebarBadges()` | Derived | Computed | Nav rail status indicator |

### Selector Pattern

All components use sliced selectors to avoid full-state re-renders:

```typescript
// ❌ Bad: subscribes to entire state
const snapshot = useSystemSnapshot();

// ✅ Good: subscribes only to drawdown
const drawdown = useSystemSnapshot(s => s.portfolio.drawdown_pct);
const assets = useSystemSnapshot(s => s.assets);
```

Governance selectors read `asset.governance.*` fields directly from the
backend snapshot — they do NOT re-derive scores independently.

### Cache Strategy

| State Type | `staleTime` | `refetchInterval` | Notes |
|------------|-------------|-------------------|-------|
| State bundle | 4s / 25s | 5s / 30s | Market open / closed |
| Health | 15s | 30s | Liveness check |
| Attribution | 25s | 30s | Lower priority |
| Trades | 25s | 30s | Paginated, slower refresh |
| Narrative | 5min | 5min | Weekly data |
| Optimization | 5min | 5min | Drift detector output |

When `market_closed` transitions from `false→true`, an immediate refetch
is triggered. Sequence ID gaps (engine restart) bypass staleTime and
force a fresh fetch.

## Visual Design

### Terminal-Precision Theme

| Token | Value | Usage |
|-------|-------|-------|
| Background | `#07080b` | Deep dark ink |
| Accent | `#3dd9ae` | Lifted emerald for primary actions |
| Mono | System monospace | All data displays |
| Surfaces | Hairline 1px borders | Panel separation at rest |
| Shadows | Single elevation token | Modal chrome only |

### Design Principles

1. **Single accent** (lifted emerald) reserved for primary actions and one-shot highlights
2. **Governance semantic** colors (green/yellow/red) only on values that signal state
3. **Mono supremacy** — all data values in monospace
4. **Hairline rules** between cells on desktop; no shadow contrast between same-elevation panels
5. **Operator voice** — concise, active, domain-specific copy

## Security

- Optional bearer token auth via `EIGENCAPITAL_API_TOKEN` env var
- Static files (HTML/CSS/JS) exempt from auth
- Auth required for all JSON API and POST endpoints
- CORS restricted to `http://127.0.0.1:3000` (Vite dev) + same-origin
- Server binds to `127.0.0.1` by default

## API Endpoints

All backend endpoints are documented in `docs/API.md`. The primary data flow
is `GET /state-bundle.json` → sliced via React Query selectors → memoized
components. Secondary endpoints poll at lower frequencies (30-60s).
