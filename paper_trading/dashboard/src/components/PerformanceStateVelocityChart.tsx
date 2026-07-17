import { useMemo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import Panel from './ui/Panel'
import EmptyState from './ui/EmptyState'

function velocityColor(v: number): string {
  const abs = Math.abs(v)
  if (abs < 0.001) return 'var(--color-gov-green)'
  if (abs < 0.005) return 'var(--color-gov-yellow)'
  return 'var(--color-gov-red)'
}

function degradationColor(v: number): string {
  if (v < 0.3) return 'var(--color-gov-green)'
  if (v < 0.6) return 'var(--color-gov-yellow)'
  return 'var(--color-gov-red)'
}

/** Compact sparkline bar showing velocity direction and magnitude. */
function VelocitySparkline({ value, label }: { value: number; label: string }) {
  const abs = Math.abs(value)
  const barWidth = Math.min(abs * 2000, 100) // Scale to show meaningful differences
  const isNegative = value < 0
  const positive = value >= 0
  const color = velocityColor(abs)

  return (
    <div className="flex items-center gap-1.5 w-full" title={`${label}: ${value.toFixed(4)}`}>
      <div className="flex-1 h-1.5 bg-panel rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{
            width: `${barWidth}%`,
            backgroundColor: color,
            marginLeft: isNegative ? `${100 - barWidth}%` : '0%',
          }}
        />
      </div>
      <span className="text-[9px] font-mono tabular-nums w-12 text-right shrink-0" style={{ color }}>
        {positive ? '+' : ''}{value.toFixed(2)}
      </span>
    </div>
  )
}

/** Performance state velocity metrics: PnL velocity/acceleration, vol, degradation, and execution with context sparklines. */
export default function PerformanceStateVelocityChart() {
  const { data: portfolio } = useSystemSnapshot(systemSelectors.portfolio)
  const v = portfolio?.pek?.performance_state?.velocity

  const cards = useMemo(() => {
    if (!v) return null
    const pnlV = typeof v.pnl_velocity === 'number' ? v.pnl_velocity : 0
    const pnlA = typeof v.pnl_acceleration === 'number' ? v.pnl_acceleration : 0
    const volV = typeof v.vol_velocity === 'number' ? v.vol_velocity : 0
    const degV = typeof v.degradation_velocity === 'number' ? v.degradation_velocity : 0
    const execV = typeof v.execution_velocity === 'number' ? v.execution_velocity : 0.5
    return [
      { label: 'PnL Velocity', value: pnlV, accent: velocityColor(pnlV) },
      { label: 'PnL Acceleration', value: pnlA, accent: velocityColor(pnlA) },
      { label: 'Vol Velocity', value: volV, accent: velocityColor(volV) },
      { label: 'Degradation Velocity', value: degV, accent: degradationColor(degV) },
      { label: 'Execution Velocity', value: execV, accent: velocityColor(execV - 0.5) },
    ]
  }, [v])

  if (!cards) {
    return (
      <Panel padding="md">
        <EmptyState message="Performance velocity unavailable" compact />
      </Panel>
    )
  }

  return (
    <Panel padding="md">
      <div className="space-y-3">
        <span className="text-2xs text-tertiary font-medium uppercase tracking-wider block">Performance State Velocity</span>
        <div className="space-y-2">
          {cards.map(c => (
            <div key={c.label} className="flex items-center gap-2">
              <span className="text-2xs text-tertiary w-28 shrink-0">{c.label}</span>
              <VelocitySparkline value={c.value} label={c.label} />
            </div>
          ))}
        </div>
        <p className="text-[9px] text-muted/60 italic mt-1">
          Positive values indicate favorable trend direction
        </p>
      </div>
    </Panel>
  )
}
