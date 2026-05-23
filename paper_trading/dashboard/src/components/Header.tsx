import { useEffect, useState } from 'react'
import { Sun, Moon, RefreshCw, Calendar, Clock, TrendingUp } from 'lucide-react'
import { usePortfolioState } from '../hooks/usePortfolioState'
import { useSessionClock } from '../hooks/useSessionClock'
import { useQueryClient } from '@tanstack/react-query'

export default function Header() {
  const { dataUpdatedAt, isError, isFetching, data } = usePortfolioState()
  const { timeStr, dateStr, marketsOpen } = useSessionClock()
  const [dark, setDark] = useState(() => localStorage.getItem('theme') !== 'light')

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    localStorage.setItem('theme', dark ? 'dark' : 'light')
  }, [dark])

  const staleness = dataUpdatedAt ? Date.now() - dataUpdatedAt : Infinity
  const isLive = !isError && staleness <= 35_000
  const isDelayed = !isError && staleness > 35_000 && staleness <= 120_000
  const statusClass = isError
    ? 'border-gov-red/25 bg-gov-red-muted text-gov-red'
    : isDelayed
      ? 'border-gov-yellow/25 bg-gov-yellow-muted text-gov-yellow'
      : 'border-gov-green/25 bg-gov-green-muted text-gov-green'
  const statusText = isError ? 'Disconnected' : isDelayed ? 'Delayed' : 'Live'
  const daysRunning = data?.portfolio?.days_running ?? 0
  const queryClient = useQueryClient()
  const [refreshing, setRefreshing] = useState(false)

  const handleRefresh = async () => {
    setRefreshing(true)
    await queryClient.invalidateQueries()
    setTimeout(() => setRefreshing(false), 800)
  }

  return (
    <header className="sticky top-0 z-30 glass glass-border">
      <div className="max-w-[90rem] mx-auto px-4 sm:px-6 py-2.5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-accent-emerald to-emerald-700 flex items-center justify-center shadow-glow-emerald">
            <TrendingUp className="w-4 h-4 text-surface" strokeWidth={2.25} />
          </div>
          <div>
            <h1 className="text-sm font-bold tracking-tight text-primary leading-none">QuantForge</h1>
            <p className="text-2xs text-muted uppercase tracking-widest mt-0.5 hidden sm:block">Paper Trading</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 sm:gap-3">
          <div className={`flex items-center gap-1.5 px-2 py-1 rounded-md border transition-colors ${statusClass}`}>
            <span className={`relative inline-flex w-1.5 h-1.5 rounded-full bg-current ${isLive ? 'animate-pulse' : ''}`}>
              {isLive && (
                <span className="absolute inset-0 rounded-full bg-current animate-ping opacity-30" />
              )}
            </span>
            <span className="text-2xs font-semibold font-mono uppercase tracking-wide">{statusText}</span>
            {isFetching && (
              <RefreshCw className="w-2.5 h-2.5 animate-spin opacity-70" strokeWidth={2.5} />
            )}
          </div>

          <div className="hidden sm:flex items-center gap-2 text-2xs text-secondary border-l border-default pl-3">
            <Calendar className="w-3 h-3 text-muted shrink-0" strokeWidth={1.5} />
            <span>{dateStr}</span>
            <Clock className="w-3 h-3 text-muted shrink-0 ml-1" strokeWidth={1.5} />
            <span className="font-mono tabular-nums">{timeStr}</span>
            <span
              className={`px-1.5 py-0.5 rounded text-2xs font-bold tracking-wider ${
                marketsOpen
                  ? 'bg-gov-green-muted text-gov-green border border-gov-green/20'
                  : 'bg-gov-red-muted text-gov-red border border-gov-red/20'
              }`}
            >
              {marketsOpen ? 'OPEN' : 'CLSD'}
            </span>
          </div>

          <div className="hidden md:flex items-center gap-1 text-2xs text-tertiary font-mono tabular-nums">
            <span className="text-muted">RUN</span>
            <span className="text-secondary">{daysRunning > 0 ? `${daysRunning}d` : '—'}</span>
          </div>

          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="p-1.5 rounded-md border border-default hover:border-strong hover:bg-panel transition-colors disabled:opacity-40 active:scale-95"
            title="Refresh all data"
          >
            <RefreshCw
              className={`w-3.5 h-3.5 text-secondary ${refreshing ? 'animate-spin' : ''}`}
              strokeWidth={2}
            />
          </button>

          <button
            type="button"
            onClick={() => setDark(d => !d)}
            className="p-1.5 rounded-md border border-default hover:border-strong hover:bg-panel transition-colors active:scale-95"
            title="Toggle theme"
          >
            {dark ? (
              <Sun className="w-3.5 h-3.5 text-gov-yellow" strokeWidth={2} />
            ) : (
              <Moon className="w-3.5 h-3.5 text-tertiary" strokeWidth={2} />
            )}
          </button>
        </div>
      </div>
    </header>
  )
}
