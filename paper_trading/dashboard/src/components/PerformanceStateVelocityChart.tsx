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

export default function PerformanceStateVelocityChart() {
  const { data: portfolio } = useSystemSnapshot(systemSelectors.portfolio)
  const v = portfolio?.pek?.performance_state?.velocity

  const cards = useMemo(() => {
    if (!v) return null
    return [
      { label: 'PnL Velocity', value: v.pnl_velocity.toFixed(4), accent: velocityColor(v.pnl_velocity) },
      { label: 'PnL Acceleration', value: v.pnl_acceleration.toFixed(4), accent: velocityColor(v.pnl_acceleration) },
      { label: 'Vol Velocity', value: v.vol_velocity.toFixed(4), accent: velocityColor(v.vol_velocity) },
      { label: 'Degradation Velocity', value: v.degradation_velocity.toFixed(4), accent: degradationColor(v.degradation_velocity) },
      { label: 'Execution Velocity', value: v.execution_velocity.toFixed(4), accent: velocityColor(v.execution_velocity - 0.5) },
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
