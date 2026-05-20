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
import Footer from './components/Footer'

export default function App() {
  return (
    <div className="min-h-screen bg-app text-secondary">
      <div className="fixed inset-0 pointer-events-none opacity-[0.03]" style={{
        backgroundImage: 'radial-gradient(currentColor 1px, transparent 1px)',
        backgroundSize: '32px 32px',
      }} />
      <Header />

      <main className="max-w-7xl mx-auto px-6 py-6 space-y-6 relative">
        <PortfolioSummary />
        <AssetGrid />
        <HaltConditions />

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <SignalsTable />
          <EquityChart />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <MetricsGrid />
          </div>
          <div className="space-y-6">
            <ConfidenceChart />
            <VolRegimePanel />
          </div>
        </div>

        <TradeFeed />
      </main>

      <Footer />
    </div>
  )
}
