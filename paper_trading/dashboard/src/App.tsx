import { HashRouter, Routes, Route, Navigate } from 'react-router-dom'
import { SelectedAssetProvider } from './hooks/useSelectedAsset'
import AppShell from './components/layout/AppShell'
import ErrorBoundary from './components/ErrorBoundary'

import DashboardOverview from './pages/DashboardOverview'
import TradingWorkspace from './pages/TradingWorkspace'
import ExecutionWorkspace from './pages/ExecutionWorkspace'
import RiskWorkspace from './pages/RiskWorkspace'

import AssetDetailPanel from './components/AssetDetailPanel'
import AssetDeepDive from './components/AssetDeepDive'
import WeeklyReviewModal from './components/WeeklyReviewModal'

import { SystemHealthModalProvider } from './hooks/useSystemHealthModal'
import SystemHealthModal from './components/SystemHealthModal'
import { useSystemSnapshot } from './hooks/useSystemSnapshot'
import { useSelectedAsset } from './hooks/useSelectedAsset'

function AppContent() {
  const { data: bundle } = useSystemSnapshot()
  const state = bundle?.snapshot
  const { selectedAsset, deepDiveAsset, setSelectedAsset, setDeepDiveAsset } = useSelectedAsset()

  const detailAsset = selectedAsset && state?.assets?.[selectedAsset]

  return (
    <>
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardOverview />} />
        <Route path="/trading" element={<TradingWorkspace />} />
        <Route path="/execution" element={<ExecutionWorkspace />} />
        <Route path="/risk" element={<RiskWorkspace />} />
      </Routes>

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
