import { memo, useState, useEffect } from 'react'
import { Menu, RefreshCw, TrendingUp } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { useEngineHealth } from '../hooks/useEngineHealth'
import { useSystemHealthModal } from '../hooks/useSystemHealthModal'
import { systemSelectors } from '../selectors/system'
import ThemeToggle from './ui/ThemeToggle'
import MT5Status from './MT5Status'

interface HeaderProps {
  onMenuClick?: () => void
}

function HealthBadge() {
  const health = useEngineHealth()
  const { open: openSystemHealth } = useSystemHealthModal()
  const engineAlive = health.data?.engine_alive ?? false
  const label = health.isError ? 'Disconnected' : health.isLoading ? '...' : engineAlive ? 'Live' : 'Stale'
  const dot = health.isError ? 'bg-gov-red' : engineAlive ? 'bg-gov-green' : 'bg-gov-yellow'

  return (
    <button
      type="button"
      onClick={openSystemHealth}
      className="min-h-[44px] min-w-[44px] flex items-center justify-center gap-1.5 px-2 rounded-md border border-default hover:border-strong hover:bg-panel transition-colors active:scale-95 focus-ring text-2xs font-mono tabular-nums"
      title={`Engine: ${label} — click for details`}
      aria-label="Open system health monitor"
    >
      <span className={`relative inline-flex w-2 h-2 rounded-full ${dot}`} />
      <span className="hidden sm:inline text-tertiary">{label}</span>
    </button>
  )
}

function Header({ onMenuClick }: HeaderProps) {
  const { data: snapshot, dataUpdatedAt } = useSystemSnapshot(systemSelectors.snapshot)
  const queryClient = useQueryClient()
  const [refreshing, setRefreshing] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const sequenceId = snapshot?.sequence_id

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
      <div className="max-w-[90rem] mx-auto px-2 sm:px-6 py-1.5 flex items-center justify-between gap-1 sm:gap-2">
        <div className="flex items-center gap-1.5 sm:gap-2 min-w-0">
          <button
            type="button"
            onClick={onMenuClick}
            className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-md border border-default hover:border-strong hover:bg-panel transition-colors lg:hidden active:scale-95 focus-ring"
            title="Toggle navigation"
            aria-label="Toggle navigation"
          >
            <Menu className="w-3.5 h-3.5 text-secondary" strokeWidth={2} />
          </button>
          <div className="w-6 h-6 sm:w-7 sm:h-7 rounded-lg bg-accent-emerald/90 flex items-center justify-center shrink-0 shadow-sm">
            <TrendingUp className="w-3 h-3 sm:w-3.5 sm:h-3.5 text-[#08090c]" strokeWidth={2.25} />
          </div>
          <div className="min-w-0">
            <div className="flex items-baseline gap-1.5">
              <h1 className="text-xs sm:text-sm font-bold tracking-tight text-primary leading-none truncate">Quorrin</h1>
              {sequenceId != null && (
                <span className="hidden sm:inline text-[8px] text-tertiary/40 font-mono leading-none">#{sequenceId}</span>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1 sm:gap-2">
          <HealthBadge />
          <ThemeToggle />
          <MT5Status />

          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-md border border-default hover:border-strong hover:bg-panel transition-colors disabled:opacity-40 active:scale-95 focus-ring"
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
