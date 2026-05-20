import { useEffect, useState } from 'react'
import { usePortfolioState } from '../hooks/usePortfolioState'
import { useSessionClock } from '../hooks/useSessionClock'

export default function Header() {
  const { dataUpdatedAt, isError, data } = usePortfolioState()
  const { timeStr, dateStr, marketsOpen } = useSessionClock()
  const [dark, setDark] = useState(() => localStorage.getItem('theme') !== 'light')

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    localStorage.setItem('theme', dark ? 'dark' : 'light')
  }, [dark])

  const staleness = dataUpdatedAt ? Date.now() - dataUpdatedAt : Infinity
  const isLive = !isError && staleness <= 35_000
  const isDelayed = !isError && staleness > 35_000 && staleness <= 120_000
  const statusColor = isError ? 'text-red-400' : isDelayed ? 'text-amber-400' : 'text-emerald-400'
  const statusText = isError ? 'Disconnected' : isDelayed ? 'Delayed' : 'Live'
  const daysRunning = data?.portfolio?.days_running ?? 0

  return (
    <header className="sticky top-0 z-30 glass glass-border border-t-0 border-x-0">
      <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-400 to-emerald-600 flex items-center justify-center">
              <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
              </svg>
            </div>
            <div>
              <h1 className="text-base font-bold tracking-tight text-primary">QuantForge</h1>
              <span className="text-[10px] text-tertiary font-mono">v2 · macro-driven</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-5">
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border ${isError ? 'border-red-500/20 bg-red-500/5' : isDelayed ? 'border-amber-500/20 bg-amber-500/5' : 'border-emerald-500/20 bg-emerald-500/5'}`}>
            <span className={`relative inline-flex w-2 h-2 rounded-full ${statusColor} ${isLive ? 'animate-pulse' : ''}`}>
              {isLive && (
                <span className={`absolute inset-0 rounded-full ${statusColor} animate-ping opacity-30`} />
              )}
            </span>
            <span className={`text-[11px] font-medium font-mono ${statusColor}`}>{statusText}</span>
          </div>

          <div className="flex items-center gap-3 text-[11px] text-secondary">
            <div className="flex items-center gap-2">
              <svg className="w-3.5 h-3.5 text-tertiary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
              </svg>
              <span>{dateStr}</span>
              <span className="font-mono text-secondary">{timeStr}</span>
            </div>
            <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
              marketsOpen ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
            }`}>
              {marketsOpen ? 'OPEN' : 'CLOSED'}
            </span>
          </div>

          <div className="flex items-center gap-2 text-[11px] text-secondary">
            <svg className="w-3.5 h-3.5 text-tertiary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span className="font-mono text-secondary">{daysRunning > 0 ? `${daysRunning}d` : '—'}</span>
          </div>

          <button
            onClick={() => setDark(d => !d)}
            className="p-1.5 rounded-lg border border-default hover:border-strong transition-colors bg-surface"
            title="Toggle theme"
          >
            {dark ? (
              <svg className="w-3.5 h-3.5 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
              </svg>
            ) : (
              <svg className="w-3.5 h-3.5 text-tertiary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
              </svg>
            )}
          </button>
        </div>
      </div>
    </header>
  )
}
