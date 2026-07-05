# EigenCapital — Dashboard Architecture

**Last updated:** 2026-07-05

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
| Routing | React Router | Client-side SPA routing |
| State | React Query | Server-state caching + polling |
| Validation | Zod | API response schema validation |
| Styling | Tailwind CSS | Utility-first styling |
| Charts | Recharts | Equity curves, PnL waterfall |
| Icons | Lucide React | UI icons |

## Route Structure

| Route | Page Component | Primary Job |
|-------|---------------|-------------|
| `/` | `CommandCenter` | Glance surface: status row, ticker rail, equity curve sparkline, open positions grid, sortable asset list |
| `/trading` | `TradingWorkspace` | Operate surface: signal queue, admission/rejected, recent trades, execution feed |
| `/execution` | `ExecutionWorkspace` | Quality surface: equity chart, execution quality KPIs, trade attribution |
| `/risk` | `RiskWorkspace` | Governance surface: PEK telemetry, portfolio risk, governance state, health scores |

All routes are lazy-loaded via `React.lazy()` + dynamic `import()`.

## Component Tree

```
<App>
  <QueryClientProvider>
    <BrowserRouter>
      <AppShell>                          ← Persistent shell, mounts on every route
        <TickerRail />                    ← 32px mono breadcrumb: EC · seq N · engine state · assets N
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
    </BrowserRouter>
  </QueryClientProvider>
</App>
```

### AppShell Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `TickerRail` | `layout/TickerRail.tsx` | Persistent status bar: sequence ID, engine state (alive/stale/dead), tick interval, PEK intents/admitted, halt status, asset count |
| `Sidebar` | `layout/Sidebar.tsx` | Navigation rail with route links and engine status chip |
| `HealthBadge` | `HealthBadge.tsx` | Header engine health indicator (icon-only click target) |
| `EmergencyHaltBanner` | `EmergencyHaltBanner.tsx` | Red banner shown during emergency halt states |
| `ConnectionStatus` | `ConnectionStatus.tsx` | Multi-endpoint liveness monitor (Live/Degraded/Offline) |
| `AlertFeed` | `monitor/AlertFeed.tsx` | Real-time governance event capture tray |

### CommandCenter Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `EquityCurveSparkline` | `EquityCurveSparkline.tsx` | 80px SVG equity curve from `/equity_history.json` |
| `StatCard` | `ui/StatCard.tsx` | KPI/metric display card (merged from old KpiCard + MetricCard) |
| `AssetCard` | `AssetCard.tsx` | Per-asset summary card with layers badge, sell-only badge, adaptive exit state |
| `AssetMiniGrid` | `AssetMiniGrid.tsx` | Compact grid of AssetCards for open positions |
| `SectionHeader` | `ui/SectionHeader.tsx` | Section title with static 1px accent dot |

### TradingWorkspace Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `SignalsTable` | `SignalsTable.tsx` | Live signal queue with confidence, direction, asset |
| `AdmissionPanel` | `AdmissionPanel.tsx` | PEK admission: intents, admitted, rejected counts |
| `TradeOutcomes` | `TradeOutcomes.tsx` | TP/SL/win rate aggregates |
| `TradingAssetRow` | `TradingAssetRow.tsx` | Dense per-asset sortable table row |

### ExecutionWorkspace Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `EquityChart` | `EquityChart.tsx` | Full Recharts area chart with drawdown and per-asset overlays |
| `ExecutionQualityStrip` | `execution/ExecutionQualityStrip.tsx` | EIS and FQI KPI row |
| `AttributionBreakdownCard` | `attribution/AttributionBreakdownCard.tsx` | Domain scores grid + PnL waterfall |
| `MaeMfeScatter` | `attribution/MaeMfeScatter.tsx` | MAE/MFE scatter plot colored by archetype |
| `FillQualityGauge` | `execution/FillQualityGauge.tsx` | SVG arc gauge for composite FQI |
| `SlippageHistogram` | `execution/SlippageHistogram.tsx` | Entry/exit slippage distribution |
| `TradeExecutionTable` | `execution/TradeExecutionTable.tsx` | Full attribution field table |

### RiskWorkspace Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `GovernanceRadar` | `GovernanceRadar.tsx` | Per-asset governance summary with halt state |
| `GovernanceStateCards` | `GovernanceStateCards.tsx` | Per-asset halted status, validity state, tooltips |
| `RiskParityPanel` | `RiskParityPanel.tsx` | Bar chart of target allocations colored by governance state |
| `PSIDriftCard` | `PSIDriftCard.tsx` | Per-asset PSI drift table with feature rows |
| `PositionConcentrationPanel` | `PositionConcentrationPanel.tsx` | Net-short skew visualization |
| `FactorExposureBreakdown` | `FactorExposureBreakdown.tsx` | 10 factor group exposure bars |
| `CalibrationCurve` | `CalibrationCurve.tsx` | Calibration reliability diagram |
| `HealthScores` | `HealthScores.tsx` | Statistical metrics: PSR, DSR, MinTRL |

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
| `useEngineHealth()` | `/health` | 5s | Liveness indicator + sequence ID |
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
| Health | 2s | 5s | Fast liveness check |
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
