import { useMemo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import StatCard from './ui/StatCard'
import Panel from './ui/Panel'
import EmptyState from './ui/EmptyState'
import { MetricCardSkeleton } from './ui/Skeleton'
import { formatTimeAgo } from '../utils/format'

export default function PortfolioSummary() {
  const { data: bundle, isPending, isError } = useSystemSnapshot()
  const snapshot = bundle?.snapshot
  const p = snapshot?.portfolio
  const mt5Equity = bundle?.live?.mt5?.account?.portfolio_value
  const lastUpdate = p?.last_update ?? snapshot?.engine_status?.last_update ?? snapshot?.timestamp

  const cards = useMemo(() => {
    if (!p) return []
    const posReturn = (p.total_return ?? 0) >= 0
    const posRealized = (p.realized_return ?? 0) >= 0
    return [
      {
        label: 'Paper Value',
        value: `$${(p.total_value ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
        sub: `Capital $${(p.capital ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
        accent: '#22c55e',
      },
      ...(mt5Equity != null ? [{
        label: 'MT5 Equity',
        value: `$${mt5Equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
        sub: 'Broker account',
        accent: '#60a5fa',
      }] : []),
      {
        label: 'Total Return %',
        value: `${(p.total_return ?? 0).toFixed(2)}%`,
        sub: `Unrealized $${(p.unrealized_pnl ?? 0).toFixed(2)}`,
        accent: posReturn ? '#22c55e' : '#ef4444',
      },
      {
        label: 'Realized P&L %',
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
  }, [p, mt5Equity])

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
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2 text-2xs text-tertiary font-mono">
        <span className="tabular-nums">
          {lastUpdate ? `Snapshot ${formatTimeAgo(lastUpdate)}` : 'Snapshot time unavailable'}
        </span>
        <span className="tabular-nums">
          {p?.start_date ? `Since ${p.start_date}` : 'Return window unavailable'}
        </span>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-2.5">
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
    </div>
  )
}
