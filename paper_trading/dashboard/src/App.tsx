import { Suspense, lazy } from 'react'
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom'
import { SelectedAssetProvider } from './hooks/useSelectedAsset'
import AppShell from './components/layout/AppShell'
import ErrorBoundary from './components/ErrorBoundary'
import { Skeleton } from './components/ui/Skeleton'
import { ToastProvider } from './components/toast/Toast'
import { CommandPaletteProvider } from './hooks/useCommandPalette'
import CommandPalette from './components/CommandPalette'
import { useGlobalShortcuts } from './hooks/useGlobalShortcuts'

const DashboardOverview = lazy(() => import('./pages/DashboardOverview'))
const TradingWorkspace = lazy(() => import('./pages/TradingWorkspace'))
const ExecutionWorkspace = lazy(() => import('./pages/ExecutionWorkspace'))
const RiskWorkspace = lazy(() => import('./pages/RiskWorkspace'))
const TradesWorkspace = lazy(() => import('./pages/TradesWorkspace'))
const MonitorWorkspace = lazy(() => import('./pages/MonitorWorkspace'))
const AnalyticsWorkspace = lazy(() => import('./pages/AnalyticsWorkspace'))

import AssetDetailPanel from './components/AssetDetailPanel'
import AssetDeepDive from './components/AssetDeepDive'
import WeeklyReviewModal from './components/WeeklyReviewModal'

import { SystemHealthModalProvider } from './hooks/useSystemHealthModal'
import SystemHealthModal from './components/SystemHealthModal'
import { useSystemSnapshot } from './hooks/useSystemSnapshot'
import { systemSelectors } from './selectors/system'
import { useSelectedAsset } from './hooks/useSelectedAsset'

function AppContent() {
  const { data: state } = useSystemSnapshot(systemSelectors.snapshot)
  const { selectedAsset, deepDiveAsset, setSelectedAsset, setDeepDiveAsset } = useSelectedAsset()

  const detailAsset = selectedAsset && state?.assets?.[selectedAsset]

  return (
    <>
      <Suspense
        fallback={
          <div className="p-8 space-y-4" aria-label="Loading page">
            <Skeleton className="h-6 w-48 rounded-lg" shimmer />
            <Skeleton className="h-64 rounded-lg" shimmer />
            <Skeleton className="h-40 rounded-lg" shimmer />
          </div>
        }
      >
        <Routes>
          <Route path="/" element={<Navigate to="/overview" replace />} />
          <Route path="/overview" element={<DashboardOverview />} />
          <Route path="/dashboard" element={<Navigate to="/overview" replace />} />
          <Route path="/trading" element={<TradingWorkspace />} />
          <Route path="/trades" element={<TradesWorkspace />} />
          <Route path="/execution" element={<ExecutionWorkspace />} />
          <Route path="/risk" element={<RiskWorkspace />} />
          <Route path="/monitor" element={<MonitorWorkspace />} />
          <Route path="/analytics" element={<AnalyticsWorkspace />} />
        </Routes>
      </Suspense>

      {detailAsset && (
        <AssetDetailPanel
          asset={detailAsset}
          name={selectedAsset!}
          onClose={() => setSelectedAsset(null)}
        />
      )}
      {deepDiveAsset && (
        <AssetDeepDive
          name={deepDiveAsset}
          onClose={() => setDeepDiveAsset(null)}
        />
      )}
      <WeeklyReviewModal />
      <SystemHealthModal />
    </>
  )
}

function ShortcutsBootstrap() {
  useGlobalShortcuts()
  return null
}

export default function App() {
  return (
    <ErrorBoundary title="Application">
      <HashRouter>
        <ToastProvider>
          <CommandPaletteProvider>
            <SelectedAssetProvider>
              <SystemHealthModalProvider>
                <AppShell>
                  <ShortcutsBootstrap />
                  <CommandPalette />
                  <AppContent />
                </AppShell>
              </SystemHealthModalProvider>
            </SelectedAssetProvider>
          </CommandPaletteProvider>
        </ToastProvider>
      </HashRouter>
    </ErrorBoundary>
  )
}
