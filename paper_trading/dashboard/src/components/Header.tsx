import { useState, useEffect } from 'react'
import { Menu, RefreshCw, TrendingUp } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { useEngineHealth } from '../hooks/useEngineHealth'
import ThemeToggle from './ui/ThemeToggle'
import MT5Status from './MT5Status'
import { formatTimeAgo } from '../utils/format'

interface HeaderProps {
  onMenuClick?: () => void
}

export default function Header({ onMenuClick }: HeaderProps) {
  const { data: bundle, isError, dataUpdatedAt } = useSystemSnapshot()
  const data = bundle?.snapshot
  const health = useEngineHealth()
  const queryClient = useQueryClient()
  const [refreshing, setRefreshing] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const lastServerUpdate = data?.portfolio?.last_update ?? data?.engine_status?.last_update ?? data?.timestamp
  const lastClientUpdate = dataUpdatedAt ? new Date(dataUpdatedAt).toISOString() : ''
  const freshnessLabel = lastServerUpdate
    ? `Updated ${formatTimeAgo(lastServerUpdate)}`
    : lastClientUpdate
      ? `Fetched ${formatTimeAgo(lastClientUpdate)}`
      : ''

  const engineAlive = health.data?.engine_alive ?? false
  const healthLabel = health.isError
    ? 'Disconnected'
    : health.isLoading
      ? '...'
      : engineAlive
        ? 'Live'
        : 'Stale'
  const healthDot = health.isError
    ? 'bg-gov-red'
    : engineAlive
      ? 'bg-gov-green'
      : 'bg-gov-yellow'

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

        <div className="flex items-center gap-2">
          <span className="hidden sm:inline-flex items-center gap-1.5 text-2xs text-tertiary font-mono tabular-nums">
            <span
              className={`relative inline-flex w-2 h-2 rounded-full ${healthDot}`}
              title={`Engine: ${healthLabel}${freshnessLabel ? ` — ${freshnessLabel}` : ''}`}
              aria-label={`Engine: ${healthLabel}${freshnessLabel ? ` — ${freshnessLabel}` : ''}`}
            />
            {healthLabel}
          </span>
          <span
            className={`sm:hidden relative inline-flex w-2 h-2 rounded-full ${healthDot}`}
            title={`Engine: ${healthLabel}${freshnessLabel ? ` — ${freshnessLabel}` : ''}`}
            aria-label={`Engine: ${healthLabel}${freshnessLabel ? ` — ${freshnessLabel}` : ''}`}
          />

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
