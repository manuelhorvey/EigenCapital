import { memo, useState, useEffect } from 'react'
import { Menu, RefreshCw, TrendingUp, Activity } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { useEngineHealth } from '../hooks/useEngineHealth'
import { useSystemHealthModal } from '../hooks/useSystemHealthModal'
import { systemSelectors } from '../selectors/system'
import MT5Status from './MT5Status'

interface HeaderProps {
  onMenuClick?: () => void
}

/**
 * Header is the chrome band above the page content. After Phase 8.1
 * the engine state is already visible at all times via the
 * TickerRail at the top of every page, and after Phase 4 the
 * Sidebar's bottom caption reads the engine state too. A third
 * visible pill in the Header would be redundant.
 *
 * HealthButton therefore collapses to an icon-only click target
 * that opens the SystemHealthModal — the visual cue is the activity
 * icon, with the runtime tone (green/yellow/red) of that icon
 * encoding the engine state. The status text is no longer readable
 * visually in the band; it remains in the title and aria-label so
 * keyboard / screen-reader users get the state.
 */
function HealthButton() {
  const health = useEngineHealth()
  const { open: openSystemHealth } = useSystemHealthModal()
  const engineAlive = health.data?.engine_alive ?? false
  const state = health.isError ? 'dead' : health.isLoading ? 'loading' : engineAlive ? 'alive' : 'stale'
  const tone = state === 'alive' ? 'text-gov-green'
    : state === 'stale' ? 'text-gov-yellow'
    : state === 'dead' ? 'text-gov-red'
    : 'text-tertiary'

  return (
    <button
      type="button"
      onClick={openSystemHealth}
      className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-md border border-default hover:border-strong hover:bg-panel transition-colors active:scale-95 focus-ring"
      title={`Engine ${state}`}
      aria-label={`Engine status: ${state}. Open details.`}
    >
      <Activity className={`w-3.5 h-3.5 ${tone}`} strokeWidth={2} />
    </button>
  )
}

function Header({ onMenuClick }: HeaderProps) {
  const { data: snapshot } = useSystemSnapshot(systemSelectors.snapshot)
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
            className="lg:hidden min-h-[44px] min-w-[44px] flex items-center justify-center rounded-md border border-default hover:border-strong hover:bg-panel transition-colors active:scale-95 focus-ring"
            title="Menu"
            aria-label="Open navigation menu"
          >
            <Menu className="w-3.5 h-3.5 text-secondary" strokeWidth={2} />
          </button>
          <div className="w-6 h-6 sm:w-7 sm:h-7 rounded-lg bg-accent-emerald/90 flex items-center justify-center shrink-0 shadow-sm">
            <TrendingUp className="w-3 h-3 sm:w-3.5 sm:h-3.5 text-[#08090c]" strokeWidth={2.25} />
          </div>
        </div>

        <div className="flex items-center gap-1 sm:gap-2">
          <HealthButton />
          <MT5Status />

          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-md border border-default hover:border-strong hover:bg-panel transition-colors disabled:opacity-40 active:scale-95 focus-ring"
            title="Refresh"
            aria-label="Refresh dashboard data"
          >
            <RefreshCw className={`w-3 h-3 text-secondary ${refreshing ? 'animate-spin' : ''}`} strokeWidth={2} />
          </button>
        </div>
      </div>
    </header>
  )
}

export default memo(Header)
