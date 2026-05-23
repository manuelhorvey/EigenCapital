import { usePortfolioState } from './hooks/usePortfolioState'
import Header from './components/Header'
import PortfolioSummary from './components/PortfolioSummary'
import AssetGrid from './components/AssetGrid'
import SignalsTable from './components/SignalsTable'
import MetricsGrid from './components/MetricsGrid'
import HaltConditions from './components/HaltConditions'
import TradeFeed from './components/TradeFeed'
import EquityChart from './components/EquityChart'
import ConfidenceChart from './components/ConfidenceChart'
import VolRegimePanel from './components/VolRegimePanel'
import HealthScores from './components/HealthScores'
import GovernancePanel from './components/GovernancePanel'
import TradeOutcomes from './components/TradeOutcomes'
import EngineLogs from './components/EngineLogs'
import Footer from './components/Footer'
import LoadingScreen from './components/ui/LoadingScreen'
import ErrorScreen from './components/ui/ErrorScreen'

export default function App() {
  const { isPending, isError } = usePortfolioState()

  if (isPending) {
    return <LoadingScreen />
  }

  if (isError) {
    return <ErrorScreen />
  }

  return (
    <div className="min-h-screen bg-app text-secondary flex flex-col">
      <div className="fixed inset-0 pointer-events-none opacity-[0.35] dark:opacity-[0.2] grid-dot" />
      <Header />

      <main className="flex-1 max-w-[90rem] w-full mx-auto px-4 sm:px-6 py-5 sm:py-6 space-y-5 sm:space-y-6 relative animate-fade-in">
        <PortfolioSummary />
        <AssetGrid />
        <HaltConditions />

        <GovernancePanel />

        <div className="grid grid-cols-1 xl:grid-cols-5 gap-4 sm:gap-5">
          <div className="xl:col-span-3 min-w-0">
            <SignalsTable />
          </div>
          <div className="xl:col-span-2 min-w-0">
            <EquityChart />
          </div>
        </div>

        <HealthScores />

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 sm:gap-5">
          <div className="lg:col-span-2 min-w-0">
            <MetricsGrid />
          </div>
          <div className="space-y-4 sm:space-y-5 min-w-0">
            <ConfidenceChart />
            <VolRegimePanel />
          </div>
        </div>

        <TradeOutcomes />
        <TradeFeed />
        <EngineLogs />
      </main>

      <Footer />
    </div>
  )
}
