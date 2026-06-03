import { useState, useEffect } from 'react'
import { RefreshCw, TrendingUp } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { usePortfolioState } from '../hooks/usePortfolioState'

export default function Header() {
  const { isError } = usePortfolioState()
  const queryClient = useQueryClient()
  const [refreshing, setRefreshing] = useState(false)
  const [scrolled, setScrolled] = useState(false)

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
          <div className="w-7 h-7 rounded-lg bg-accent-emerald/90 flex items-center justify-center shrink-0">
            <TrendingUp className="w-3.5 h-3.5 text-[#08090c]" strokeWidth={2.25} />
          </div>
          <div className="min-w-0">
            <h1 className="text-sm font-bold tracking-tight text-primary leading-none truncate">QuantForge</h1>
            <p className="text-[11px] text-tertiary font-medium mt-0.5">Paper Trading</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span
            className={`relative inline-flex w-2 h-2 rounded-full ${isError ? 'bg-gov-red' : 'bg-gov-green'}`}
            title={isError ? 'Disconnected' : 'Connected'}
          />

          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="p-1.5 rounded-md border border-default hover:border-strong hover:bg-panel transition-colors disabled:opacity-40 active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-emerald/50"
            title="Refresh all data"
          >
            <RefreshCw className={`w-3 h-3 text-secondary ${refreshing ? 'animate-spin' : ''}`} strokeWidth={2} />
          </button>
        </div>
      </div>
    </header>
  )
}
