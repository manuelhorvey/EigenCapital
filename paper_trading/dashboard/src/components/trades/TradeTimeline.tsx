import { Zap, ShieldCheck, TrendingUp, Flag } from 'lucide-react'
import type { TradeAttributionRecord } from '../../hooks/useAttributionTrades'

interface TimelineEvent {
  icon: typeof Zap
  time: string
  type: string
  color: string
  lines: { label: string; value: string; color?: string }[]
}

interface TradeTimelineProps {
  data: TradeAttributionRecord
}

/** Vertical timeline visualizing signal generation, governance check, entry, and exit events for a trade.
 * @param {TradeAttributionRecord} data - Attribution record containing trade events */
export default function TradeTimeline({ data }: TradeTimelineProps) {
  const events: TimelineEvent[] = [
    {
      icon: Zap,
      time: data.entry_date,
      type: 'SIGNAL',
      color: 'text-accent-blue',
      lines: [
        { label: 'Signal', value: data.pred_signal },
        { label: 'Confidence', value: `${(data.pred_confidence * 100).toFixed(0)}%` },
        { label: 'Archetype', value: data.pred_archetype_at_entry },
        { label: 'Regime', value: data.pred_regime_at_entry },
      ],
    },
    {
      icon: ShieldCheck,
      time: data.entry_date,
      type: 'GOVERNANCE CHECK',
      color: 'text-accent-emerald',
      lines: [
        { label: 'Direction Correct', value: data.pred_forecast_direction_correct === null ? '—' : data.pred_forecast_direction_correct ? 'Yes' : 'No', color: data.pred_forecast_direction_correct ? 'text-signal-long' : 'text-signal-short' },
      ],
    },
    {
      icon: TrendingUp,
      time: data.entry_date,
      type: 'ENTRY',
      color: 'text-accent-purple',
      lines: [
        { label: 'Price', value: `$${data.entry_price.toFixed(2)}` },
        { label: 'Type', value: data.exec_entry_type },
        { label: 'Slippage', value: `${data.friction_entry_slippage_bps.toFixed(1)} bps`, color: data.friction_entry_slippage_bps > 5 ? 'text-signal-short' : 'text-signal-long' },
        { label: 'Fill', value: `${((data.friction_fill_qty_ratio ?? 1) * 100).toFixed(0)}%` },
      ],
    },
    {
      icon: Flag,
      time: data.exit_date,
      type: 'EXIT',
      color: 'text-signal-warn',
      lines: [
        { label: 'Reason', value: data.exit_exit_reason ?? '' },
        { label: 'Realized R', value: data.exit_realized_r.toFixed(2), color: data.exit_realized_r >= 0 ? 'text-signal-long' : 'text-signal-short' },
        { label: 'MAE / MFE', value: `${data.exit_mae.toFixed(1)} / ${data.exit_mfe.toFixed(1)}` },
        { label: 'Bars Held', value: String(data.exit_bars_held) },
      ],
    },
  ]

  return (
    <div className="relative pl-6 space-y-0">
      {/* Vertical line */}
      <div className="absolute left-[11px] top-2 bottom-2 w-px bg-border" />

      {events.map((event) => (
        <div key={event.type} className="relative pb-4 last:pb-0">
          {/* Dot */}
          <div className={`absolute -left-[19px] top-0.5 w-[15px] h-[15px] rounded-full bg-app border-2 border-default flex items-center justify-center ${event.color}`}>
            <event.icon className="w-2 h-2" strokeWidth={2.5} />
          </div>

          {/* Content */}
          <div className="bg-surface border border-default rounded-lg px-3 py-2">
            <div className="flex items-center gap-2 mb-1.5">
              <span className={`text-2xs font-bold uppercase tracking-wider ${event.color}`}>{event.type}</span>
              <span className="text-2xs text-tertiary font-mono">{event.time}</span>
            </div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-2xs">
              {event.lines.map(line => (
                <div key={line.label} className="flex items-center gap-1">
                  <span className="text-tertiary">{line.label}:</span>
                  <span className={`font-medium ${line.color ?? 'text-secondary'}`}>{line.value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
