import { useTradingState } from '../lib/trading-state/hook'
import Panel from './ui/Panel'
import Badge from './ui/Badge'
import StatCard from './ui/StatCard'
import { Skeleton } from './ui/Skeleton'

const statusConfig = {
  SAFE: { variant: 'success' as const, label: 'SAFE' },
  MONITOR: { variant: 'warning' as const, label: 'MONITOR' },
  ALERT: { variant: 'error' as const, label: 'ALERT' },
} as const

export default function SystemHealthSummary() {
  const { portfolio, isLoading } = useTradingState()

  if (isLoading || !portfolio) {
    return (
      <Panel padding="md">
        <div className="flex items-center gap-3">
          <Skeleton className="h-6 w-20 rounded" shimmer />
          <Skeleton className="h-4 w-32 rounded" shimmer />
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5 mt-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded" shimmer />
          ))}
        </div>
      </Panel>
    )
  }

  const cfg = statusConfig[portfolio.system_status]
  const pnlColor = portfolio.pnl.total >= 0 ? '#22c55e' : '#ef4444'
  const mt5Color = portfolio.execution.mt5_sync === 'HEALTHY' ? '#22c55e' : '#eab308'

  return (
    <Panel padding="md" variant={portfolio.system_status === 'ALERT' ? 'accent' : 'default'}>
      {/* Status row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <Badge variant={cfg.variant} size="md" glow>
            {cfg.label}
          </Badge>
          <span className="text-xs text-tertiary">
            {portfolio.alerts.length > 0
              ? portfolio.alerts[0]
              : 'All systems nominal'}
          </span>
        </div>
        {portfolio.alerts.length > 1 && (
          <span className="text-[10px] text-tertiary">
            +{portfolio.alerts.length - 1} more
          </span>
        )}
      </div>

      {/* Key metrics row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5">
        <StatCard
          label="PnL"
          value={`${portfolio.pnl.total >= 0 ? '+' : ''}${portfolio.pnl.total.toFixed(2)}`}
          sub={`Eff: ${(portfolio.pnl.efficiency * 100).toFixed(0)}%`}
          accent={pnlColor}
          variant="compact"
        />
        <StatCard
          label="Drawdown"
          value={`${(portfolio.risk.drawdown * 100).toFixed(1)}%`}
          sub={`Conc: ${portfolio.risk.concentration_risk.toLowerCase()}`}
          accent={portfolio.risk.drawdown > 0.05 ? '#eab308' : '#22c55e'}
          variant="compact"
        />
        <StatCard
          label="MT5 Sync"
          value={portfolio.execution.mt5_sync}
          sub={`SL: ${portfolio.execution.sl_sync_integrity}`}
          accent={mt5Color}
          variant="compact"
        />
        <StatCard
          label="Edge Health"
          value={portfolio.alpha.edge_trend}
          sub={portfolio.alpha.reversal_rate != null
            ? `Rev: ${(portfolio.alpha.reversal_rate * 100).toFixed(0)}%`
            : 'No data'}
          variant="compact"
        />
      </div>

      {/* Top risks */}
      {portfolio.top_3_risks.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-3">
          {portfolio.top_3_risks.map((risk) => (
            <Badge
              key={risk.title}
              variant={risk.severity === 'CRITICAL' ? 'error' : risk.severity === 'HIGH' ? 'warning' : 'neutral'}
              size="sm"
            >
              {risk.title}
            </Badge>
          ))}
        </div>
      )}
    </Panel>
  )
}
