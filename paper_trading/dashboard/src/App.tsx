import { Suspense, lazy, useCallback, useEffect, useRef } from 'react'
import { HashRouter, Routes, Route } from 'react-router-dom'
import { SelectedAssetProvider } from './hooks/useSelectedAsset'
import { ModalStackProvider, useModalStack } from './hooks/useModalStack'
import { ThemeProvider } from './hooks/useTheme'
import { ToastProvider } from './hooks/useToast'
import { NotificationProvider } from './hooks/useNotificationCenter'
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

// Preload all page bundles after mount via <link rel="modulepreload"> so
// chunk fetches happen in the background and navigation is instant. Uses
// import.meta.url to resolve relative paths to absolute module URLs that
// the browser's module loader can fetch and cache without executing.
function useRoutePreloader() {
  useEffect(() => {
    const routes = [
      './pages/CommandCenter',
      './pages/TradingWorkspace',
      './pages/ExecutionWorkspace',
      './pages/RiskWorkspace',
    ]
    for (const route of routes) {
      const link = document.createElement('link')
      link.rel = 'modulepreload'
      link.href = new URL(route, import.meta.url).href
      document.head.appendChild(link)
    }
    // Preload heavy overlay components when browser is idle (no modulepreload
    // equivalent for these — they're imported directly in the render tree so
    // they'd be double-fetched; idle-load them as fallback).
    import('./components/AssetDetailPanel').catch(() => {})
    import('./components/AssetDeepDive').catch(() => {})
    import('./components/SystemHealthModal').catch(() => {})
    import('./components/WeeklyReviewModal').catch(() => {})
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

import { useToastAlertBridge } from './hooks/useToastAlertBridge'

function AppContent() {
  useRoutePreloader()
  useToastAlertBridge()
  const { data: state } = useSystemSnapshot(systemSelectors.snapshot)
  const { selectedAsset, deepDiveAsset, setSelectedAsset, setDeepDiveAsset } = useSelectedAsset()
  const { push, pop } = useModalStack()

  // Stable callback identities (`useCallback`) preserve `React.memo` on
  // memo-wrapped children (CommandCenter page, AssetDetailPanel,
  // AssetDeepDive). Without this, every AppContent render cascades a
  // new function ref to all memo'd children, defeating their cache.
  const handleSelectAsset = useCallback(
    (name: string) => setSelectedAsset(name),
    [setSelectedAsset]
  )
  const handleCloseDetail = useCallback(
    () => {
      setSelectedAsset(null)
      pop('asset-detail')
    },
    [setSelectedAsset, pop]
  )
  const handleCloseDeepDive = useCallback(
    () => {
      setDeepDiveAsset(null)
      pop('asset-deep-dive')
    },
    [setDeepDiveAsset, pop]
  )

  // Sync URL-based selection state to modal stack. The stack ensures
  // ordered overlay rendering with a single backdrop (F9 fix).
  const prevDetailRef = useRef(selectedAsset)
  const prevDeepDiveRef = useRef(deepDiveAsset)

  useEffect(() => {
    if (selectedAsset && !deepDiveAsset) {
      push({
        id: 'asset-detail',
        component: AssetDetailPanel,
        props: { asset: state?.assets?.[selectedAsset], name: selectedAsset, onClose: handleCloseDetail },
      })
    } else if (!selectedAsset && prevDetailRef.current) {
      pop('asset-detail')
    }
    prevDetailRef.current = selectedAsset
  }, [selectedAsset, deepDiveAsset, state?.assets, handleCloseDetail, push, pop])

  useEffect(() => {
    if (deepDiveAsset) {
      push({
        id: 'asset-deep-dive',
        component: AssetDeepDive,
        props: { name: deepDiveAsset, onClose: handleCloseDeepDive },
      })
    } else if (!deepDiveAsset && prevDeepDiveRef.current) {
      pop('asset-deep-dive')
    }
    prevDeepDiveRef.current = deepDiveAsset
  }, [deepDiveAsset, handleCloseDeepDive, push, pop])

  // Re-push detail entry when asset data updates to keep props fresh
  useEffect(() => {
    if (selectedAsset && !deepDiveAsset && state?.assets?.[selectedAsset]) {
      push({
        id: 'asset-detail',
        component: AssetDetailPanel,
        props: { asset: state.assets[selectedAsset], name: selectedAsset, onClose: handleCloseDetail },
      })
    }
  }, [state?.assets, selectedAsset, deepDiveAsset, handleCloseDetail, push])

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
      <NotificationProvider>
      <HashRouter>
        <SelectedAssetProvider>
          <SystemHealthModalProvider>
          <ModalStackProvider>
          <AppShell>
            <AppContent />
          </AppShell>
          </ModalStackProvider>
          </SystemHealthModalProvider>
        </SelectedAssetProvider>
      </HashRouter>
      </NotificationProvider>
      </ToastProvider>
      </ThemeProvider>
    </ErrorBoundary>
  )
}
