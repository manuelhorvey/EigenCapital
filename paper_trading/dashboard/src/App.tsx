import { useEffect, useState } from 'react'
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
import GovernanceStateCards from './components/GovernanceStateCards'
import HitRateDrift from './components/HitRateDrift'
import RiskParityPanel from './components/RiskParityPanel'
import PSIDriftCard from './components/PSIDriftCard'
import EngineLogs from './components/EngineLogs'
import AlertFeed from './components/AlertFeed'
import Footer from './components/Footer'
import LoadingScreen from './components/ui/LoadingScreen'
import ErrorScreen from './components/ui/ErrorScreen'
import ErrorBoundary from './components/ErrorBoundary'

const NAV_SECTIONS = [
  { id: 'portfolio', label: 'Portfolio' },
  { id: 'signals', label: 'Signals' },
  { id: 'trades', label: 'Trades' },
  { id: 'governance', label: 'Governance' },
  { id: 'risk', label: 'Risk' },
  { id: 'charts', label: 'Charts' },
]

function AnchorNav() {
  const [active, setActive] = useState('portfolio')

  useEffect(() => {
    const observer = new IntersectionObserver(
      entries => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActive(entry.target.id)
        }
      },
      { rootMargin: '-80px 0px -60% 0px', threshold: 0 },
    )

    for (const { id } of NAV_SECTIONS) {
      const el = document.getElementById(id)
      if (el) observer.observe(el)
    }

    return () => observer.disconnect()
  }, [])

  return (
    <nav className="sticky top-[45px] sm:top-[49px] z-20 bg-app/80 backdrop-blur-md border-b border-default/60">
      <div className="max-w-[90rem] mx-auto px-3 sm:px-6 flex items-center gap-0 overflow-x-auto scrollbar-none">
        {NAV_SECTIONS.map(({ id, label }) => (
          <a
            key={id}
            href={`#${id}`}
            onClick={e => {
              e.preventDefault()
              document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
            }}
            className={`shrink-0 px-3 py-1.5 text-2xs font-medium transition-colors border-b-2 ${
              active === id
                ? 'text-primary border-accent-emerald'
                : 'text-tertiary border-transparent hover:text-secondary hover:border-default/40'
            }`}
          >
            {label}
          </a>
        ))}
      </div>
    </nav>
  )
}

export default function App() {
  const { isPending, isError, isFetching } = usePortfolioState()

  if (isPending) return <LoadingScreen />
  if (isError) return <ErrorScreen />

  return (
    <div className="min-h-screen bg-app text-secondary flex flex-col">
      <div className="fixed inset-0 pointer-events-none opacity-[0.35] dark:opacity-[0.2] grid-dot" />
      <Header />
      <AnchorNav />

      <main
        className="flex-1 max-w-[90rem] w-full mx-auto px-4 sm:px-6 py-5 sm:py-6 space-y-5 sm:space-y-6 relative animate-fade-in"
        data-fetching={isFetching ? 'true' : undefined}
      >
        <ErrorBoundary title="Portfolio">
          <section id="portfolio" className="anchor-nav space-y-5 sm:space-y-6">
            <PortfolioSummary />
            <AssetGrid />
            <HaltConditions />
          </section>
        </ErrorBoundary>

        <ErrorBoundary title="Governance">
          <section id="governance" className="anchor-nav space-y-5 sm:space-y-6">
            <GovernancePanel />
            <GovernanceStateCards />
            <RiskParityPanel />
            <PSIDriftCard />
          </section>
        </ErrorBoundary>

        <ErrorBoundary title="Signals">
          <section id="signals" className="anchor-nav">
            <div className="grid grid-cols-1 xl:grid-cols-5 gap-4 sm:gap-5">
              <div className="xl:col-span-3 min-w-0">
                <SignalsTable />
              </div>
              <div className="xl:col-span-2 min-w-0">
                <EquityChart />
              </div>
            </div>
          </section>
        </ErrorBoundary>

        <ErrorBoundary title="Risk">
          <section id="risk" className="anchor-nav">
            <HealthScores />
          </section>
        </ErrorBoundary>

        <ErrorBoundary title="Charts">
          <section id="charts" className="anchor-nav">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 sm:gap-5">
              <div className="lg:col-span-2 min-w-0">
                <MetricsGrid />
              </div>
              <div className="space-y-4 sm:space-y-5 min-w-0">
                <ConfidenceChart />
                <HitRateDrift />
                <VolRegimePanel />
              </div>
            </div>
          </section>
        </ErrorBoundary>

        <ErrorBoundary title="Trades">
          <section id="trades" className="anchor-nav space-y-5 sm:space-y-6">
            <TradeOutcomes />
            <TradeFeed />
          </section>
        </ErrorBoundary>

        <ErrorBoundary title="Alert Feed">
          <AlertFeed />
        </ErrorBoundary>

        <ErrorBoundary title="Engine Logs">
          <EngineLogs />
        </ErrorBoundary>
      </main>

      <Footer />
    </div>
  )
}
