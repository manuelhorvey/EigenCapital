import { memo, useState, useEffect } from 'react'
import { Menu, RefreshCw, TrendingUp, DollarSign, Activity } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { useEngineHealth } from '../hooks/useEngineHealth'
import { useSystemHealthModal } from '../hooks/useSystemHealthModal'
import ThemeToggle from './ui/ThemeToggle'
import MT5Status from './MT5Status'
import { formatTimeAgo } from '../utils/format'

function EngineDot() {
  const health = useEngineHealth()
  const engineAlive = health.data?.engine_alive ?? false
  const label = health.isError ? 'Disconnected' : health.isLoading ? '...' : engineAlive ? 'Live' : 'Stale'
  const dot = health.isError ? 'bg-gov-red' : engineAlive ? 'bg-gov-green' : 'bg-gov-yellow'
  return (
    <span className="hidden sm:inline-flex items-center gap-1.5 text-2xs text-tertiary font-mono tabular-nums">
      <span
        className={`relative inline-flex w-2 h-2 rounded-full ${dot}`}
        title={`Engine: ${label}`}
        aria-label={`Engine: ${label}`}
      />
      {label}
    </span>
  )
}

function EngineDotMobile() {
  const health = useEngineHealth()
  const engineAlive = health.data?.engine_alive ?? false
  const label = health.isError ? 'Disconnected' : health.isLoading ? '...' : engineAlive ? 'Live' : 'Stale'
  const dot = health.isError ? 'bg-gov-red' : engineAlive ? 'bg-gov-green' : 'bg-gov-yellow'
  return (
    <span
      className={`sm:hidden relative inline-flex w-2 h-2 rounded-full ${dot}`}
      title={`Engine: ${label}`}
      aria-label={`Engine: ${label}`}
    />
  )
}

const QuickStatsBar = memo(function QuickStatsBar() {
  const { data: bundle } = useSystemSnapshot()
  const portfolio = bundle?.snapshot?.portfolio
  if (!portfolio) return null

  const pnl = portfolio.mtm_value - portfolio.capital
  const pnlPct = portfolio.capital > 0 ? (pnl / portfolio.capital) * 100 : 0

  return (
    <div className="hidden md:flex items-center gap-4 text-2xs font-mono tabular-nums">
      <div className="flex items-center gap-1.5 text-tertiary">
        <DollarSign className="w-3 h-3 text-tertiary/60" strokeWidth={1.5} />
        <span className="text-primary font-semibold">
          {portfolio.mtm_value.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
        </span>
      </div>
      <span className={`${pnlPct >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
        {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
      </span>
      <span className="text-tertiary">
        {portfolio.open_positions} pos
      </span>
    </div>
  )
})

interface HeaderProps {
  onMenuClick?: () => void
}

function Header({ onMenuClick }: HeaderProps) {
  const { data: bundle, dataUpdatedAt } = useSystemSnapshot()
  const data = bundle?.snapshot
  const queryClient = useQueryClient()
  const [refreshing, setRefreshing] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const { open: openSystemHealth } = useSystemHealthModal()
  const lastServerUpdate = data?.portfolio?.last_update ?? data?.engine_status?.last_update ?? data?.timestamp
  const lastClientUpdate = dataUpdatedAt ? new Date(dataUpdatedAt).toISOString() : ''
  const freshnessLabel = lastServerUpdate
    ? `Updated ${formatTimeAgo(lastServerUpdate)}`
    : lastClientUpdate
      ? `Fetched ${formatTimeAgo(lastClientUpdate)}`
      : ''

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 10)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  const handleRefresh = async () => {
    setRefreshing(true)
    await queryClient.invalidateQueries()
    setTimeout(() => setRefreshing(false), 800)
  }

  return (
    <header
      className={`sticky top-0 z-30 bg-app/90 backdrop-blur-md border-b transition-shadow duration-200 ${
        scrolled ? 'border-default shadow-[0_1px_0_rgba(255,255,255,0.04)]' : 'border-default/60'
      }`}
    >
      <div className="max-w-[90rem] mx-auto px-4 sm:px-7 py-2.5 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onMenuClick}
            className="p-1.5 rounded-md border border-default hover:border-strong hover:bg-panel transition-colors lg:hidden active:scale-95 focus-ring"
            title="Toggle navigation"
            aria-label="Toggle navigation"
          >
            <Menu className="w-3.5 h-3.5 text-secondary" strokeWidth={2} />
          </button>
          <div className="w-8 h-8 rounded-lg bg-accent-emerald/90 flex items-center justify-center shrink-0 shadow-sm">
            <TrendingUp className="w-4 h-4 text-[#08090c]" strokeWidth={2.25} />
          </div>
          <div className="min-w-0">
            <h1 className="text-sm font-bold tracking-tight text-primary leading-none truncate">QuantForge</h1>
            <p className="text-[9px] text-tertiary font-mono tracking-wider uppercase leading-none mt-0.5">Paper Trading</p>
          </div>
        </div>

        <QuickStatsBar />

        <div className="flex items-center gap-2">
          <EngineDot />
          <EngineDotMobile />

          <button
            type="button"
            onClick={openSystemHealth}
            className="p-1.5 rounded-md border border-default hover:border-strong hover:bg-panel transition-colors active:scale-95 focus-ring hidden sm:inline-flex"
            title="System Health"
            aria-label="Open system health monitor"
          >
            <Activity className="w-3.5 h-3.5 text-secondary" strokeWidth={2} />
          </button>
          <ThemeToggle />
          <MT5Status />

          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="p-1.5 rounded-md border border-default hover:border-strong hover:bg-panel transition-colors disabled:opacity-40 active:scale-95 focus-ring"
            title="Refresh all data"
            aria-label="Refresh all dashboard data"
          >
            <RefreshCw className={`w-3 h-3 text-secondary ${refreshing ? 'animate-spin' : ''}`} strokeWidth={2} />
          </button>
        </div>
      </div>
    </header>
  )
}

export default memo(Header)
