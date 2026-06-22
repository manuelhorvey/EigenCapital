import { useState } from 'react'
import { usePortfolioState } from './hooks/usePortfolioState'
import { SelectedAssetContext } from './hooks/useSelectedAsset'
import Header from './components/Header'
import PortfolioSummary from './components/PortfolioSummary'
import AssetGrid from './components/AssetGrid'
import SignalsTable from './components/SignalsTable'
import HaltConditions from './components/HaltConditions'
import TradeFeed from './components/TradeFeed'
import EquityChart from './components/EquityChart'
import HealthScores from './components/HealthScores'
import TradeOutcomes from './components/TradeOutcomes'
import LoadingScreen from './components/ui/LoadingScreen'
import ErrorScreen from './components/ui/ErrorScreen'
import Section from './components/ui/Section'
import ExecutionQualityStrip from './components/execution/ExecutionQualityStrip'
import AttributionBreakdownCard from './components/attribution/AttributionBreakdownCard'
import PnLWaterfall from './components/attribution/PnLWaterfall'
import MaeMfeScatter from './components/attribution/MaeMfeScatter'
import SlippageHistogram from './components/execution/SlippageHistogram'
import FillQualityGauge from './components/execution/FillQualityGauge'
import TradeExecutionTable from './components/execution/TradeExecutionTable'
import MonitoringDashboard from './components/monitor/MonitoringDashboard'
import GovernanceRadar from './components/governance/GovernanceRadar'

import WeeklyReviewModal from './components/WeeklyReviewModal'
import AssetDetailPanel from './components/AssetDetailPanel'
import AssetDeepDive from './components/AssetDeepDive'
import ExecutionFeed from './components/ExecutionFeed'

import Sidebar from './components/layout/Sidebar'
import ErrorBoundary from './components/ErrorBoundary'

type TabId = 'dashboard' | 'trading' | 'execution' | 'risk'

export default function App() {
  const { data: state, isPending, isError } = usePortfolioState()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [selectedAsset, setSelectedAsset] = useState<string | null>(null)
  const [deepDiveAsset, setDeepDiveAsset] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<TabId>('dashboard')

  if (isPending) return <LoadingScreen />
  if (isError) return <ErrorScreen />

  const detailAsset = selectedAsset && state?.assets?.[selectedAsset]

  const tabContent: Record<TabId, React.ReactNode> = {
    dashboard: (
      <div className="space-y-6 sm:space-y-8">
        <MonitoringDashboard />
        <PortfolioSummary />
        <HaltConditions />
      </div>
    ),
    trading: (
      <div className="space-y-6 sm:space-y-8">
        <Section id="signals" errorTitle="Signals">
          <div className="grid grid-cols-1 xl:grid-cols-5 gap-5 sm:gap-6">
            <div className="xl:col-span-3 min-w-0">
              <SignalsTable />
            </div>
            <div className="xl:col-span-2 min-w-0">
              <EquityChart />
            </div>
          </div>
        </Section>
        <Section id="trades" errorTitle="Trades">
          <TradeOutcomes />
          <TradeFeed />
        </Section>
        <Section id="execution-feed" errorTitle="Execution Feed">
          <ExecutionFeed />
        </Section>
      </div>
    ),
    execution: (
      <div className="space-y-6 sm:space-y-8">
        <Section id="execution-quality" errorTitle="Execution Quality" className="space-y-5 sm:space-y-6">
          <ExecutionQualityStrip />
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 sm:gap-6">
            <div className="lg:col-span-2 min-w-0">
              <SlippageHistogram />
            </div>
            <div className="lg:col-span-1 min-w-0">
              <FillQualityGauge />
            </div>
          </div>
          <TradeExecutionTable />
        </Section>
        <Section id="trade-attribution" errorTitle="Trade Attribution" className="space-y-5 sm:space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 sm:gap-6">
            <AttributionBreakdownCard />
            <PnLWaterfall />
          </div>
          <MaeMfeScatter />
        </Section>
      </div>
    ),
    risk: (
      <div className="space-y-6 sm:space-y-8">
        <Section id="portfolio-risk" errorTitle="Portfolio Risk">
          <HealthScores />
        </Section>
        <Section id="governance" errorTitle="Governance Constraints">
          <GovernanceRadar />
        </Section>
        <Section id="asset-grid" errorTitle="All Assets">
          <AssetGrid />
        </Section>
      </div>
    ),
  }

  return (
    <ErrorBoundary title="Application">
      <SelectedAssetContext.Provider value={{ selectedAsset, setSelectedAsset, deepDiveAsset, setDeepDiveAsset }}>
        <div className="min-h-screen bg-app text-secondary flex flex-col">
          <Header onMenuClick={() => setSidebarOpen(prev => !prev)} />

          <div className="flex-1 flex relative max-w-[90rem] mx-auto w-full">
            <Sidebar open={sidebarOpen} activeTab={activeTab} onTabChange={setActiveTab} onClose={() => setSidebarOpen(false)} />

            <main className="flex-1 min-w-0 px-4 sm:px-7 py-5 sm:py-7 animate-fade-in">
              {tabContent[activeTab]}
            </main>
          </div>
        </div>
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
      </SelectedAssetContext.Provider>
    </ErrorBoundary>
  )
}
