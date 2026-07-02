import Badge from '../ui/Badge'
import { toBadgeConfig } from '../../lib/ui/governance-status'
import type { TradeAttributionRecord } from '../../types/attribution'

interface TradeGovernanceAuditProps {
  data: TradeAttributionRecord
}

interface AuditEntry {
  layer: string
  status: 'pass' | 'warn' | 'fail'
  impact: number
  detail: string
}

function computeAudit(data: TradeAttributionRecord): AuditEntry[] {
  const entries: AuditEntry[] = []

  // Direction correctness
  if (data.pred_forecast_direction_correct !== null) {
    entries.push({
      layer: 'Direction Forecast',
      status: data.pred_forecast_direction_correct ? 'pass' : 'fail',
      impact: data.pred_forecast_direction_correct ? 0 : -1,
      detail: data.pred_forecast_direction_correct ? 'Direction correct' : 'Direction incorrect',
    })
  }

  // Slippage
  const totalSlippage = data.friction_entry_slippage_bps + data.friction_exit_slippage_bps
  entries.push({
    layer: 'Slippage Control',
    status: totalSlippage > 10 ? 'fail' : totalSlippage > 5 ? 'warn' : 'pass',
    impact: -totalSlippage / 100,
    detail: `${totalSlippage.toFixed(1)} bps total slippage`,
  })

  // Fill quality
  if (data.friction_fill_qty_ratio != null) {
    entries.push({
      layer: 'Fill Quality',
      status: data.friction_fill_qty_ratio < 0.8 ? 'fail' : data.friction_fill_qty_ratio < 0.95 ? 'warn' : 'pass',
      impact: -((1 - data.friction_fill_qty_ratio) * 100) / 100,
      detail: `${(data.friction_fill_qty_ratio * 100).toFixed(0)}% filled`,
    })
  }

  // Gap fill
  if (data.friction_gap_fill) {
    entries.push({
      layer: 'Gap Fill',
      status: 'warn',
      impact: -0.3,
      detail: 'Trade executed on gap fill',
    })
  }

  // Partial fill
  if (data.friction_partial_fill) {
    entries.push({
      layer: 'Partial Fill',
      status: 'fail',
      impact: -0.5,
      detail: 'Order partially filled',
    })
  }

  // Exit efficiency
  const rRatio = data.exit_realized_r / (data.exit_theoretical_r || 1)
  entries.push({
    layer: 'Exit Efficiency',
    status: rRatio >= 0.8 ? 'pass' : rRatio >= 0.5 ? 'warn' : 'fail',
    impact: rRatio - 1,
    detail: `${(rRatio * 100).toFixed(0)}% of theoretical R captured`,
  })

  return entries
}

function impactColor(impact: number): string {
  if (impact >= 0) return 'text-gov-green'
  if (impact > -0.1) return 'text-gov-yellow'
  return 'text-gov-red'
}

export default function TradeGovernanceAudit({ data }: TradeGovernanceAuditProps) {
  const audit = computeAudit(data)

  return (
    <div className="space-y-2">
      {audit.map(entry => {
        const badge = toBadgeConfig(entry.status)
        return (
          <div key={entry.layer} className="flex items-center gap-3 px-3 py-2 bg-surface border border-default rounded-lg">
            <Badge variant={badge.variant} size="sm" dot>{badge.label}</Badge>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-primary">{entry.layer}</p>
              <p className="text-2xs text-tertiary">{entry.detail}</p>
            </div>
            <span className={`text-xs font-mono font-bold tabular-nums ${impactColor(entry.impact)}`}>
              {entry.impact >= 0 ? '+' : ''}{entry.impact.toFixed(2)}
            </span>
          </div>
        )
      })}
    </div>
  )
}
