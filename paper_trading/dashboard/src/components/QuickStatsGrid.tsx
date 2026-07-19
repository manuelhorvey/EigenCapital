/** Headline metric row: portfolio value, return, drawdown, open/closed positions, peak, capital/MT5 equity. */
import { memo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { useMonitorAlerts } from '../hooks/useMonitorAlerts'
import { systemSelectors } from '../selectors/system'
import { Skeleton } from './ui/Skeleton'
import { formatTimeAgo, formatPct } from '../utils/format'
import { gridMetric7, GRID_GAP } from '../design/grid'

/** Color-coded risk tier badge. */
function RiskTierBadge({ riskPct, matchedThreshold }: { riskPct: number; matchedThreshold: number | null }) {
  const isLow = riskPct <= 1.0
  const isMid = riskPct > 1.0 && riskPct <= 1.5

  const bg = isLow ? 'bg-gov-green/10 border-gov-green/20 text-gov-green'
    : isMid ? 'bg-gov-yellow/10 border-gov-yellow/20 text-gov-yellow'
    : 'bg-gov-red/10 border-gov-red/20 text-gov-red'

  const dotColor = isLow ? 'bg-gov-green' : isMid ? 'bg-gov-yellow' : 'bg-gov-red'

  const label = matchedThreshold != null && matchedThreshold > 0
    ? `Risk ${riskPct.toFixed(1)}% (≥ $${matchedThreshold.toLocaleString()})`
    : `Risk ${riskPct.toFixed(1)}%`

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-semibold tracking-wider ${bg}`}
      title={`Active risk tier: ${riskPct.toFixed(1)}% per trade`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />
      {label}
    </span>
  )
}

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
  const { data: snapshot, error } = useSystemSnapshot(systemSelectors.snapshot)
  const p = snapshot?.portfolio
  if (error) {
    return (
      <div className={`${gridMetric7()} ${GRID_GAP}`}>
        <div className="col-span-full flex items-center justify-center h-20 rounded-lg bg-surface/50 border border-gov-red/20">
          <p className="text-gov-red text-xs font-semibold">Snapshot unavailable — {error instanceof Error ? error.message : 'Connection failed'}</p>
        </div>
      </div>
    )
  }
  const { data: mt5Live } = useSystemSnapshot(systemSelectors.mt5)
  const mt5Equity = mt5Live?.account?.portfolio_value ?? null
  const lastUpdate =
    p?.last_update ?? snapshot?.engine_status?.last_update ?? snapshot?.timestamp
  const alerts = useMonitorAlerts()
  const criticalAlerts = alerts.filter((a) => a.severity === 'critical').length
  const riskTier = p?.active_risk_tier

  if (!p) {
    return (
      <div className={`${gridMetric7()} ${GRID_GAP}`}>
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
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 pb-3 text-2xs text-tertiary font-mono tabular-nums border-b border-default">
        <span className="flex items-center gap-2">
          <span>{lastUpdate ? `Snapshot ${formatTimeAgo(lastUpdate)}` : ''}</span>
          {riskTier && (
            <RiskTierBadge riskPct={riskTier.risk_pct} matchedThreshold={riskTier.matched_threshold} />
          )}
        </span>
        <span>{p.start_date ? `Since ${p.start_date}` : ''}</span>
        {criticalAlerts > 0 && (
          <span role="status" className="text-gov-red font-semibold">
            {criticalAlerts} critical alert{criticalAlerts > 1 ? 's' : ''}
          </span>
        )}
      </div>
      <dl className={`${gridMetric7()} gap-y-3 lg:divide-x lg:divide-default`}>
        <Stat
          label="Portfolio Value"
          value={`$${(p.mtm_value ?? 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
        />
        <Stat
          label="Total Return"
          value={formatPct(totalReturn)}
          tone={posReturn ? 'good' : 'bad'}
        />
        <Stat
          label="Realized P&L"
          value={formatPct(p.realized_return ?? 0)}
          tone={posRealized ? 'good' : 'bad'}
        />
        <Stat
          label="Drawdown"
          value={formatPct(drawdownPct)}
          tone={Math.abs(drawdownPct) >= 5 ? 'bad' : Math.abs(drawdownPct) >= 1 ? 'warn' : undefined}
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
QuickStatsGrid.displayName = 'QuickStatsGrid'
export default QuickStatsGrid
