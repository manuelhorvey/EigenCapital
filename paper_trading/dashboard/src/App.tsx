import { useState } from 'react'
import { usePortfolioState } from './hooks/usePortfolioState'
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
import type { FilterState } from './components/FilterBar'
import FilterBar from './components/FilterBar'
import ExecutionQualityStrip from './components/execution/ExecutionQualityStrip'
import AttributionBreakdownCard from './components/attribution/AttributionBreakdownCard'
import PnLWaterfall from './components/attribution/PnLWaterfall'
import MaeMfeScatter from './components/attribution/MaeMfeScatter'
import SlippageHistogram from './components/execution/SlippageHistogram'
import FillQualityGauge from './components/execution/FillQualityGauge'
import TradeExecutionTable from './components/execution/TradeExecutionTable'


import { useAttributionTrades } from './hooks/useAttributionTrades'
import AnchorNav from './components/AnchorNav'
import ErrorBoundary from './components/ErrorBoundary'

export default function App() {
  const { isPending, isError } = usePortfolioState()
  const [filters, setFilters] = useState<FilterState>({ archetype: '', regime: '', asset: '' })
  const { data: allTrades } = useAttributionTrades(200)
  const uniqueAssets = [...new Set(allTrades?.map(t => t.asset) ?? [])]

  if (isPending) return <LoadingScreen />
  if (isError) return <ErrorScreen />

  return (
    <ErrorBoundary title="Application">
      <div className="min-h-screen bg-app text-secondary flex flex-col">
        <Header />
        <AnchorNav />

        <main className="flex-1 max-w-[90rem] w-full mx-auto px-4 sm:px-7 py-5 sm:py-7 space-y-6 sm:space-y-8 relative animate-fade-in">
          <Section id="portfolio" errorTitle="Portfolio">
            <PortfolioSummary />
            <AssetGrid />
            <HaltConditions />
          </Section>

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

          <Section id="execution" errorTitle="Execution" className="space-y-5 sm:space-y-6">
            <FilterBar assets={uniqueAssets} onChange={setFilters} />
            <ExecutionQualityStrip />
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 sm:gap-6">
              <AttributionBreakdownCard />
              <PnLWaterfall />
            </div>
            <MaeMfeScatter />
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

          <Section id="trades" errorTitle="Trades">
            <TradeOutcomes />
            <TradeFeed />
          </Section>

          <Section id="risk" errorTitle="Risk">
            <HealthScores />
          </Section>
        </main>
      </div>
    </ErrorBoundary>
  )
}
