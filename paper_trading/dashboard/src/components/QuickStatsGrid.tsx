/** Headline metric row: portfolio value, return, drawdown, open/closed positions, peak, capital/MT5 equity. */
import { memo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { useMonitorAlerts } from '../hooks/useMonitorAlerts'
import { systemSelectors } from '../selectors/system'
import { Skeleton } from './ui/Skeleton'
import { formatTimeAgo } from '../utils/format'

function Stat({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: 'good' | 'warn' | 'bad'
}) {
  const cls =
    tone === 'good'
      ? 'text-gov-green'
      : tone === 'warn'
      ? 'text-gov-yellow'
      : tone === 'bad'
      ? 'text-gov-red'
      : 'text-primary'
  return (
    <div className="px-3 py-2 min-w-0">
      <dt className="text-2xs text-secondary font-medium uppercase tracking-wider truncate">{label}</dt>
      <dd className={`text-base font-bold font-mono tabular-nums ${cls} mt-0.5 truncate`}>{value}</dd>
    </div>
  )
}

function QuickStatsGridInner() {
  const { data: snapshot } = useSystemSnapshot(systemSelectors.snapshot)
  const p = snapshot?.portfolio
  const { data: mt5Live } = useSystemSnapshot(systemSelectors.mt5)
  const mt5Equity = mt5Live?.account?.portfolio_value ?? null
  const lastUpdate =
    p?.last_update ?? snapshot?.engine_status?.last_update ?? snapshot?.timestamp
  const alerts = useMonitorAlerts()
  const criticalAlerts = alerts.filter((a) => a.severity === 'critical').length

  if (!p) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-7 gap-3">
        {Array.from({ length: 7 }).map((_, i) => (
          <Skeleton key={i} className="h-20 rounded-lg" shimmer />
        ))}
      </div>
    )
  }

  const totalReturn = p.total_return ?? 0
  const drawdown = p.portfolio_drawdown ?? 0
  const peakValue = p.portfolio_peak_value
  const posReturn = totalReturn >= 0
  const posRealized = (p.realized_return ?? 0) >= 0
  const drawdownPct = drawdown * 100
  const drawdownTone =
    drawdownPct >= 5 ? 'text-gov-red' : drawdownPct >= 1 ? 'text-gov-yellow' : 'text-secondary'

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 pb-3 text-2xs text-tertiary font-mono tabular-nums border-b border-default">
        <span>{lastUpdate ? `Snapshot ${formatTimeAgo(lastUpdate)}` : ''}</span>
        <span>{p.start_date ? `Since ${p.start_date}` : ''}</span>
        {criticalAlerts > 0 && (
          <span className="text-gov-red font-semibold">
            {criticalAlerts} critical alert{criticalAlerts > 1 ? 's' : ''}
          </span>
        )}
      </div>
      <dl className="grid grid-cols-2 lg:grid-cols-7 gap-y-3 lg:divide-x lg:divide-default">
        <Stat
          label="Portfolio Value"
          value={`$${(p.mtm_value ?? 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
        />
        <Stat
          label="Total Return"
          value={`${posReturn ? '+' : ''}${totalReturn.toFixed(2)}%`}
          tone={posReturn ? 'good' : 'bad'}
        />
        <Stat
          label="Realized P&L"
          value={`${posRealized ? '+' : ''}${(p.realized_return ?? 0).toFixed(2)}%`}
          tone={posRealized ? 'good' : 'bad'}
        />
        <Stat
          label="Drawdown"
          value={`-${drawdownPct.toFixed(2)}%`}
          tone={
            drawdownTone === 'text-secondary'
              ? undefined
              : drawdownPct >= 5
              ? 'bad'
              : 'warn'
          }
        />
        <Stat
          label="Open / Closed"
          value={`${p.open_positions ?? 0} / ${p.closed_trades ?? 0}`}
        />
        <Stat
          label="Peak Value"
          value={
            peakValue != null
              ? `$${peakValue.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
              : '—'
          }
        />
        <Stat
          label={mt5Equity != null ? 'MT5 Equity' : 'Capital'}
          value={
            mt5Equity != null
              ? `$${mt5Equity.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
              : `$${(p.capital ?? 0).toLocaleString(undefined, { minimumFractionDigits: 0 })}`
          }
        />
      </dl>
    </div>
  )
}

const QuickStatsGrid = memo(QuickStatsGridInner)
export default QuickStatsGrid
