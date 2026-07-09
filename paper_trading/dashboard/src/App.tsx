import { Suspense, lazy, useCallback, useEffect, useRef } from 'react'
import { HashRouter, Routes, Route } from 'react-router-dom'
import { SelectedAssetProvider } from './hooks/useSelectedAsset'
import { ThemeProvider } from './hooks/useTheme'
import { ToastProvider, useToast } from './hooks/useToast'
import { useMonitorAlerts } from './hooks/useMonitorAlerts'
import { useEngineHealth } from './hooks/useEngineHealth'
import { ToastContainer } from './components/ui/ToastContainer'
import AppShell from './components/layout/AppShell'
import ErrorBoundary from './components/ErrorBoundary'
import { Skeleton } from './components/ui/Skeleton'

const CommandCenter = lazy(() => import('./pages/CommandCenter'))
const TradingWorkspace = lazy(() => import('./pages/TradingWorkspace'))
const ExecutionWorkspace = lazy(() => import('./pages/ExecutionWorkspace'))
const RiskWorkspace = lazy(() => import('./pages/RiskWorkspace'))
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'))
const ServerErrorPage = lazy(() => import('./pages/ServerErrorPage'))
const OfflinePage = lazy(() => import('./pages/OfflinePage'))

// Preload all page bundles when the browser is idle — ensures instant
// navigation when the operator switches tabs without adding to the
// initial page load. Uses requestIdleCallback with a setTimeout fallback.
function preloadOnIdle(importFn: () => Promise<unknown>) {
  const fn = () => { importFn().catch(() => {}) }
  if ('requestIdleCallback' in window) {
    (window as Window & typeof globalThis).requestIdleCallback(fn, { timeout: 2000 })
  } else {
    setTimeout(fn, 1000)
  }
}

function useRoutePreloader() {
  useEffect(() => {
    preloadOnIdle(() => import('./pages/TradingWorkspace'))
    preloadOnIdle(() => import('./pages/ExecutionWorkspace'))
    preloadOnIdle(() => import('./pages/RiskWorkspace'))
    // Preload heavy overlay components when browser is idle
    preloadOnIdle(() => import('./components/AssetDetailPanel'))
    preloadOnIdle(() => import('./components/AssetDeepDive'))
    preloadOnIdle(() => import('./components/SystemHealthModal'))
    preloadOnIdle(() => import('./components/WeeklyReviewModal'))
  }, [])
}

const AssetDetailPanel = lazy(() => import('./components/AssetDetailPanel'))
const AssetDeepDive = lazy(() => import('./components/AssetDeepDive'))
const WeeklyReviewModal = lazy(() => import('./components/WeeklyReviewModal'))

import { SystemHealthModalProvider } from './hooks/useSystemHealthModal'
const SystemHealthModal = lazy(() => import('./components/SystemHealthModal'))
import { useSystemSnapshot } from './hooks/useSystemSnapshot'
import { systemSelectors } from './selectors/system'
import { useSelectedAsset } from './hooks/useSelectedAsset'

// ── Toast alert bridge ───────────────────────────────────────────
// Connects the existing useMonitorAlerts system (passive alert panel)
// to the real-time toast notification system. When a new critical
// alert appears, it fires a toast. This runs inside AppContent so it
// has access to both the toast dispatcher and the alert stream.
function useToastAlertBridge() {
  const alerts = useMonitorAlerts()
  const { toast } = useToast()
  const previousAlertIds = useRef<Set<string>>(new Set())

  useEffect(() => {
    const currentIds = new Set(alerts.map(a => a.id))
    for (const alert of alerts) {
      if (!previousAlertIds.current.has(alert.id)) {
        // New alert — fire a toast
        toast({
          type: alert.severity === 'critical' ? 'error' : 'warning',
          title: alert.message,
          message: alert.detail ?? undefined,
          duration: alert.severity === 'critical' ? 6000 : 4000,
        })
      }
    }
    previousAlertIds.current = currentIds
  }, [alerts, toast])

  // Also monitor engine health
  const health = useEngineHealth()
  const previousEngineDead = useRef(false)

  useEffect(() => {
    const isDead = !!(health.isError || (health.data && !health.data.engine_alive))
    if (isDead && !previousEngineDead.current) {
      toast({
        type: 'error',
        title: 'Engine connection lost',
        message: 'Dashboard data may be stale',
        duration: 0, // persistent until dismissed
      })
    } else if (!isDead && previousEngineDead.current) {
      toast({
        type: 'success',
        title: 'Engine reconnected',
        duration: 3000,
      })
    }
    previousEngineDead.current = isDead
  }, [health, toast])
}

function AppContent() {
  useRoutePreloader()
  useToastAlertBridge()
  const { data: state } = useSystemSnapshot(systemSelectors.snapshot)
  const { selectedAsset, deepDiveAsset, setSelectedAsset, setDeepDiveAsset } = useSelectedAsset()

  const detailAsset = selectedAsset && state?.assets?.[selectedAsset]

  // Stable callback identities (`useCallback`) preserve `React.memo` on
  // memo-wrapped children (CommandCenter page, AssetDetailPanel,
  // AssetDeepDive). Without this, every AppContent render cascades a
  // new function ref to all memo'd children, defeating their cache.
  const handleSelectAsset = useCallback(
    (name: string) => setSelectedAsset(name),
    [setSelectedAsset]
  )
  const handleCloseDetail = useCallback(
    () => setSelectedAsset(null),
    [setSelectedAsset]
  )
  const handleCloseDeepDive = useCallback(
    () => setDeepDiveAsset(null),
    [setDeepDiveAsset]
  )

  return (
    <>
      <Suspense fallback={<div className="p-8"><Skeleton className="h-64 rounded-lg" shimmer /></div>}>
        <Routes>
          <Route path="/" element={<CommandCenter onSelectAsset={handleSelectAsset} />} />
          <Route path="/trading" element={<TradingWorkspace />} />
          <Route path="/execution" element={<ExecutionWorkspace />} />
          <Route path="/risk" element={<RiskWorkspace />} />
          <Route path="/error" element={<ServerErrorPage />} />
          <Route path="/offline" element={<OfflinePage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>

      {/* Modal stacking fix (F9): When the deep dive is open, the detail
          panel closes — they are managed as a stack, not two independent
          overlays. The deep dive replaces the detail panel, preventing
          z-index conflicts and escape-key desync. */}
      {!deepDiveAsset && detailAsset && (
        <Suspense fallback={null}>
          <AssetDetailPanel
            asset={detailAsset}
            name={selectedAsset!}
            onClose={handleCloseDetail}
          />
        </Suspense>
      )}
      {deepDiveAsset && (
        <Suspense fallback={null}>
          <AssetDeepDive
            name={deepDiveAsset}
            onClose={handleCloseDeepDive}
          />
        </Suspense>
      )}
      <Suspense fallback={null}><WeeklyReviewModal /></Suspense>
      <Suspense fallback={null}><SystemHealthModal /></Suspense>
      <ToastContainer />
    </>
  )
}

export default function App() {
  return (
    <ErrorBoundary title="Application">
      <ThemeProvider>
      <ToastProvider>
      <HashRouter>
        <SelectedAssetProvider>
          <SystemHealthModalProvider>
          <AppShell>
            <AppContent />
          </AppShell>
          </SystemHealthModalProvider>
        </SelectedAssetProvider>
      </HashRouter>
      </ToastProvider>
      </ThemeProvider>
    </ErrorBoundary>
  )
}
