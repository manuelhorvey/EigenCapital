import { Suspense, lazy } from 'react'
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom'
import { SelectedAssetProvider } from './hooks/useSelectedAsset'
import AppShell from './components/layout/AppShell'
import ErrorBoundary from './components/ErrorBoundary'
import { Skeleton } from './components/ui/Skeleton'

const DashboardOverview = lazy(() => import('./pages/DashboardOverview'))
const TradingWorkspace = lazy(() => import('./pages/TradingWorkspace'))
const ExecutionWorkspace = lazy(() => import('./pages/ExecutionWorkspace'))
const RiskWorkspace = lazy(() => import('./pages/RiskWorkspace'))

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
      <Suspense fallback={<div className="p-8"><Skeleton className="h-64 rounded-lg" shimmer /></div>}>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardOverview />} />
          <Route path="/trading" element={<TradingWorkspace />} />
          <Route path="/execution" element={<ExecutionWorkspace />} />
          <Route path="/risk" element={<RiskWorkspace />} />
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
