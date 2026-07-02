import { useMemo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import Panel from './ui/Panel'
import EmptyState from './ui/EmptyState'

function budgetBar(current: number, max: number, label: string): { pct: number; color: string } {
  const pct = max > 0 ? (current / max) * 100 : 0
  const color = pct > 80 ? 'var(--color-gov-red)' : pct > 50 ? 'var(--color-gov-yellow)' : 'var(--color-gov-green)'
  return { pct, color }
}

export default function RiskBudgetChart() {
  const { data: portfolio } = useSystemSnapshot(systemSelectors.portfolio)
  const ps = portfolio?.pek?.portfolio_snapshot

  const bars = useMemo(() => {
    if (!ps) return null
    return [
      { label: 'Leverage Remaining', current: ps.leverage_remaining ?? 0, max: ps.max_leverage ?? 1 },
      { label: 'Concurrent Remaining', current: ps.concurrent_remaining ?? 0, max: ps.max_concurrent ?? 20 },
      { label: 'Daily Loss Remaining', current: Math.max(0, (ps.max_daily_loss ?? 0) - Math.abs(ps.daily_pnl ?? 0)), max: Math.abs(ps.max_daily_loss ?? 0) || 1 },
    ]
  }, [ps])

  if (!bars) {
    return (
      <Panel padding="md">
        <EmptyState message="Risk budget snapshot unavailable" compact />
      </Panel>
    )
  }

  return (
    <Panel padding="md">
      <div className="space-y-3">
        <span className="text-2xs text-tertiary font-medium uppercase tracking-wider">Risk Budget Snapshot</span>
        {bars.map(b => {
          const { pct, color } = budgetBar(b.current, b.max, b.label)
          return (
            <div key={b.label} className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="text-tertiary">{b.label}</span>
                <span className="font-mono text-primary tabular-nums">
                  {typeof b.current === 'number' ? b.current.toFixed(b.current % 1 === 0 ? 0 : 2) : '0'} / {b.max}
                </span>
              </div>
              <div className="h-2 bg-panel rounded overflow-hidden">
                <div
                  className="h-full rounded transition-all duration-300"
                  style={{ width: `${pct}%`, backgroundColor: color }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </Panel>
  )
}
