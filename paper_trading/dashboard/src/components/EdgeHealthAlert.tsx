import { useTradingState } from '../lib/trading-state/hook'
import Panel from './ui/Panel'
import Badge from './ui/Badge'
import StatCard from './ui/StatCard'

const trendConfig = {
  EXPANDING: { variant: 'success' as const, label: 'Expanding', color: '#22c55e' },
  STABLE: { variant: 'default' as const, label: 'Stable', color: '#22c55e' },
  DECAYING: { variant: 'warning' as const, label: 'Decaying', color: '#eab308' },
} as const

export default function EdgeHealthAlert() {
  const { portfolio, isLoading } = useTradingState()

  if (isLoading || !portfolio) {
    return (
      <Panel padding="md">
        <span className="text-xs text-tertiary">Loading edge health...</span>
      </Panel>
    )
  }

  const alpha = portfolio.alpha
  const trend = trendConfig[alpha.edge_trend]
  const ratePct = alpha.reversal_rate != null ? `${(alpha.reversal_rate * 100).toFixed(0)}%` : '—'

  return (
    <Panel padding="md">
      <div className="flex items-center justify-between mb-2.5">
        <span className="text-[11px] font-medium uppercase tracking-wider text-tertiary">
          Edge Health
        </span>
        <Badge variant={trend.variant} size="sm" dot>
          {trend.label}
        </Badge>
      </div>
      <div className="grid grid-cols-2 gap-2.5">
        <StatCard
          label="Reversal Rate"
          value={ratePct}
          sub="Losers with MFE ≥ 1R"
          accent={trend.color}
          variant="compact"
        />
        <StatCard
          label="Trend"
          value={alpha.edge_trend}
          sub={alpha.edge_trend === 'DECAYING' ? 'Monitor reversal rate' : 'Within normal range'}
          accent={trend.color}
          variant="compact"
        />
      </div>
    </Panel>
  )
}
