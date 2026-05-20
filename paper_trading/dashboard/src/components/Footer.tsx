import { usePortfolioState } from '../hooks/usePortfolioState'
import { useSessionClock } from '../hooks/useSessionClock'

export default function Footer() {
  const { data } = usePortfolioState()
  const { timeStr, marketsOpen } = useSessionClock()
  const p = data?.portfolio
  const startDate = p?.start_date
  const gateDate = startDate ? new Date(new Date(startDate).getTime() + 180 * 86400000) : null

  const sessionInfo = (() => {
    if (!data?.assets) return ''
    const names = Object.keys(data.assets).sort()
    return marketsOpen ? names.join(', ') : 'All markets closed'
  })()

  return (
    <footer className="border-t border-default px-6 py-4">
      <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-3 text-[11px] text-tertiary">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5">
            <svg className="w-3 h-3 text-tertiary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Next retrain: <span className="text-secondary font-medium">Jan 1, {new Date().getFullYear() + 1}</span>
          </span>
        </div>

        <div className="flex items-center gap-4">
          <span>
            Started: <span className="text-secondary font-medium">{startDate ? new Date(startDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '—'}</span>
          </span>
          <span>
            6-month gate: <span className="text-secondary font-medium">{gateDate ? gateDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '—'}</span>
          </span>
          <span>
            Cleared: <span className={`font-medium ${p?.deployment_cleared ? 'text-emerald-400' : 'text-amber-400'}`}>{p?.deployment_cleared ? 'Yes' : 'No'}</span>
          </span>
        </div>

        <span className="hidden md:inline truncate max-w-xs text-muted">
          {sessionInfo}
        </span>
      </div>
    </footer>
  )
}
