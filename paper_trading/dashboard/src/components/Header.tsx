import { memo, useState, useEffect } from 'react'
import { Menu, RefreshCw, TrendingUp, Search } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { useEngineHealth } from '../hooks/useEngineHealth'
import { useSystemHealthModal } from '../hooks/useSystemHealthModal'
import { useCommandPalette } from '../hooks/useCommandPalette'
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
      className="h-8 flex items-center justify-center gap-1.5 px-2 rounded-md border border-default hover:border-strong hover:bg-panel transition-colors active:scale-95 focus-ring text-2xs font-mono tabular-nums"
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
  const { open: openPalette } = useCommandPalette()
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
      <div className="max-w-[90rem] mx-auto px-2 sm:px-6 flex items-center justify-between gap-1 sm:gap-3 h-[var(--header-height)]">
        <div className="flex items-center gap-1.5 sm:gap-3 min-w-0">
          <button
            type="button"
            onClick={onMenuClick}
            className="h-8 w-8 flex items-center justify-center rounded-md border border-default hover:border-strong hover:bg-panel transition-colors lg:hidden active:scale-95 focus-ring"
            title="Toggle navigation"
            aria-label="Toggle navigation"
          >
            <Menu className="w-3.5 h-3.5 text-secondary" strokeWidth={2} />
          </button>
          <div className="w-6 h-6 rounded-lg bg-accent-amber/95 flex items-center justify-center shrink-0 shadow-sm">
            <TrendingUp className="w-3 h-3 text-[#0a0602]" strokeWidth={2.25} />
          </div>
          <div className="min-w-0">
            <div className="flex items-baseline gap-1.5">
              <h1 className="text-xs sm:text-[13px] font-bold tracking-tight text-primary leading-none truncate">Quorrin</h1>
              {sequenceId != null && (
                <span className="hidden sm:inline text-[8px] text-tertiary/40 font-mono leading-none">#{sequenceId}</span>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1 sm:gap-2">
          {/* Search / command palette trigger (desktop) */}
          <button
            type="button"
            onClick={openPalette}
            className="hidden md:flex items-center gap-2 h-8 px-2.5 rounded-md border border-default hover:border-strong hover:bg-panel transition-colors focus-ring active:scale-[0.98] text-2xs text-tertiary font-mono"
            aria-label="Open command palette"
            title="Search pages, assets, sections (⌘K)"
          >
            <Search className="w-3 h-3" strokeWidth={2} />
            <span>Search</span>
            <kbd className="hidden lg:inline-flex items-center px-1 py-px rounded border border-default bg-panel/50 text-[9px] text-tertiary">
              ⌘K
            </kbd>
          </button>

          <HealthBadge />
          <ThemeToggle />
          <MT5Status />

          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="h-8 w-8 flex items-center justify-center rounded-md border border-default hover:border-strong hover:bg-panel transition-colors disabled:opacity-40 active:scale-95 focus-ring"
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
