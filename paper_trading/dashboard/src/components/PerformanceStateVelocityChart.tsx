import { useMemo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import Panel from './ui/Panel'
import StatCard from './ui/StatCard'
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

/** Performance state velocity metrics: PnL velocity/acceleration, vol, degradation, and execution. */
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
      { label: 'PnL Velocity', value: pnlV.toFixed(4), accent: velocityColor(pnlV) },
      { label: 'PnL Acceleration', value: pnlA.toFixed(4), accent: velocityColor(pnlA) },
      { label: 'Vol Velocity', value: volV.toFixed(4), accent: velocityColor(volV) },
      { label: 'Degradation Velocity', value: degV.toFixed(4), accent: degradationColor(degV) },
      { label: 'Execution Velocity', value: execV.toFixed(4), accent: velocityColor(execV - 0.5) },
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
      <span className="text-2xs text-tertiary font-medium uppercase tracking-wider block mb-3">Performance State Velocity</span>
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-2">
        {cards.map(c => (
          <StatCard key={c.label} label={c.label} value={c.value} variant="kpi" accent={c.accent} />
        ))}
      </div>
    </Panel>
  )
}
