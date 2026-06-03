import { useMemo } from 'react'
import { usePortfolioState } from '../hooks/usePortfolioState'
import StatCard from './ui/StatCard'
import Panel from './ui/Panel'
import EmptyState from './ui/EmptyState'
import { MetricCardSkeleton } from './ui/Skeleton'

export default function PortfolioSummary() {
  const { data, isPending, isError } = usePortfolioState()
  const p = data?.portfolio

  const cards = useMemo(() => {
    if (!p) return []
    const posReturn = (p.total_return ?? 0) >= 0
    const posRealized = (p.realized_return ?? 0) >= 0
    return [
      {
        label: 'Portfolio Value',
        value: `$${(p.total_value ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
        sub: `Capital $${(p.capital ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
        accent: '#22c55e',
      },
      {
        label: 'Total Return',
        value: `${(p.total_return ?? 0).toFixed(2)}%`,
        sub: `Unrealized $${(p.unrealized_pnl ?? 0).toFixed(2)}`,
        accent: posReturn ? '#22c55e' : '#ef4444',
      },
      {
        label: 'Realized P&L',
        value: `${posRealized ? '+' : ''}${(p.realized_return ?? 0).toFixed(2)}%`,
        sub: `Realized $${(p.realized_value ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
        accent: posRealized ? '#22c55e' : '#ef4444',
      },
      {
        label: 'Positions',
        value: `${p.open_positions ?? 0} / ${p.closed_trades ?? 0}`,
        sub: 'Open / Closed',
        accent: '#60a5fa',
      },
    ]
  }, [p])

  if (isPending) {
    return <MetricCardSkeleton count={4} />
  }

  if (isError) {
    return (
      <Panel padding="md">
        <EmptyState message="Connecting to paper trading engine…" compact />
      </Panel>
    )
  }

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {cards.map(c => (
        <StatCard
          key={c.label}
          label={c.label}
          value={c.value}
          sub={c.sub}
          accent={c.accent}
        />
      ))}
    </div>
  )
}
