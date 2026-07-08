import { Suspense, lazy, useCallback, useEffect } from 'react'
import { HashRouter, Routes, Route } from 'react-router-dom'
import { SelectedAssetProvider } from './hooks/useSelectedAsset'
import AppShell from './components/layout/AppShell'
import ErrorBoundary from './components/ErrorBoundary'
import { Skeleton } from './components/ui/Skeleton'

const CommandCenter = lazy(() => import('./pages/CommandCenter'))
const TradingWorkspace = lazy(() => import('./pages/TradingWorkspace'))
const ExecutionWorkspace = lazy(() => import('./pages/ExecutionWorkspace'))
const RiskWorkspace = lazy(() => import('./pages/RiskWorkspace'))

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
  }, [])
}

import AssetDetailPanel from './components/AssetDetailPanel'
import AssetDeepDive from './components/AssetDeepDive'
import WeeklyReviewModal from './components/WeeklyReviewModal'

import { SystemHealthModalProvider } from './hooks/useSystemHealthModal'
import SystemHealthModal from './components/SystemHealthModal'
import { useSystemSnapshot } from './hooks/useSystemSnapshot'
import { systemSelectors } from './selectors/system'
import { useSelectedAsset } from './hooks/useSelectedAsset'

function AppContent() {
  useRoutePreloader()
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
        </Routes>
      </Suspense>

      {/* Modal stacking fix (F9): When the deep dive is open, the detail
          panel closes — they are managed as a stack, not two independent
          overlays. The deep dive replaces the detail panel, preventing
          z-index conflicts and escape-key desync. */}
      {!deepDiveAsset && detailAsset && (
        <AssetDetailPanel
          asset={detailAsset}
          name={selectedAsset!}
          onClose={handleCloseDetail}
        />
      )}
      {deepDiveAsset && (
        <AssetDeepDive
          name={deepDiveAsset}
          onClose={handleCloseDeepDive}
        />
      )}
      <WeeklyReviewModal />
      <SystemHealthModal />
    </>
  )
}

export default function App() {
  return (
    <ErrorBoundary title="Application">
      <HashRouter>
        <SelectedAssetProvider>
          <SystemHealthModalProvider>
          <AppShell>
            <AppContent />
          </AppShell>
          </SystemHealthModalProvider>
        </SelectedAssetProvider>
      </HashRouter>
    </ErrorBoundary>
  )
}
