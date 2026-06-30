import { useMemo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import Panel from './ui/Panel'
import StatCard from './ui/StatCard'
import { Skeleton } from './ui/Skeleton'
import EmptyState from './ui/EmptyState'

function scalarColor(v: number, threshold = 0.7): string {
  if (v >= threshold) return 'var(--color-gov-green)'
  if (v >= threshold * 0.6) return 'var(--color-gov-yellow)'
  return 'var(--color-gov-red)'
}

export default function PekScalarPanel() {
  const { data: portfolio } = useSystemSnapshot(systemSelectors.portfolio)
  const pek = portfolio?.pek

  const perfCards = useMemo(() => {
    const ps = pek?.performance_state
    if (!ps) return null
    return [
      { label: 'Velocity', value: ps.velocity_scalar.toFixed(3), accent: scalarColor(ps.velocity_scalar) },
      { label: 'Outcome', value: ps.outcome_scalar.toFixed(3), accent: scalarColor(ps.outcome_scalar) },
      { label: 'Degradation', value: ps.degradation_scalar.toFixed(3), accent: scalarColor(ps.degradation_scalar, 0.8) },
      { label: 'Market', value: ps.market_scalar.toFixed(3), accent: scalarColor(ps.market_scalar) },
      { label: 'Execution', value: ps.execution_scalar.toFixed(3), accent: scalarColor(ps.execution_scalar) },
      { label: 'Composite', value: ps.composite_scalar.toFixed(3), accent: scalarColor(ps.composite_scalar) },
    ]
  }, [pek])

  const velocityCards = useMemo(() => {
    const v = pek?.performance_state?.velocity
    if (!v || typeof v.pnl_velocity !== 'number') return null
    return [
      { label: 'PnL Velocity', value: v.pnl_velocity.toFixed(4), accent: scalarColor(Math.abs(v.pnl_velocity), 0.002) },
      { label: 'PnL Acceleration', value: v.pnl_acceleration.toFixed(4), accent: scalarColor(Math.abs(v.pnl_acceleration), 0.001) },
      { label: 'Vol Velocity', value: v.vol_velocity.toFixed(4), accent: scalarColor(1 - v.vol_velocity, 0.5) },
      { label: 'Degradation Velocity', value: v.degradation_velocity.toFixed(4), accent: scalarColor(1 - v.degradation_velocity, 0.5) },
      { label: 'Execution Velocity', value: v.execution_velocity.toFixed(4), accent: scalarColor(v.execution_velocity) },
    ]
  }, [pek])

  const budgetCards = useMemo(() => {
    const rb = pek?.risk_budget
    if (!rb) return null
    return [
      { label: 'Risk Per Trade', value: `${(rb.max_risk_per_trade_pct * 100).toFixed(2)}%`, accent: scalarColor(rb.max_risk_per_trade_pct, 0.02) },
      { label: 'Portfolio Heat', value: rb.max_portfolio_heat.toFixed(2), accent: scalarColor(rb.max_portfolio_heat, 2) },
      { label: 'Max Concurrent', value: String(rb.max_concurrent_positions), accent: scalarColor(rb.max_concurrent_positions / 20) },
      { label: 'Vol Scalar', value: rb.volatility_scalar.toFixed(3), accent: scalarColor(rb.volatility_scalar) },
      { label: 'DD Scalar', value: rb.drawdown_scalar.toFixed(3), accent: scalarColor(rb.drawdown_scalar) },
      { label: 'Perf Scalar', value: rb.performance_scalar.toFixed(3), accent: scalarColor(rb.performance_scalar) },
    ]
  }, [pek])

  const snapCards = useMemo(() => {
    const ps = pek?.portfolio_snapshot
    if (!ps) return null
    return [
      { label: 'Leverage Remaining', value: ps.leverage_remaining.toFixed(2), sub: `max ${ps.max_leverage}`, accent: scalarColor(ps.leverage_remaining, 0.5) },
      { label: 'Concurrent Remaining', value: String(ps.concurrent_remaining), sub: `max ${ps.max_concurrent}`, accent: scalarColor(ps.concurrent_remaining / ps.max_concurrent) },
      { label: 'Gross Exposure', value: `${(ps.gross_exposure * 100).toFixed(1)}%`, accent: scalarColor(1 - ps.gross_exposure / 3, 0.5) },
      { label: 'Net Exposure', value: `${(ps.net_exposure * 100).toFixed(1)}%`, accent: scalarColor(1 - Math.abs(ps.net_exposure), 0.7) },
    ]
  }, [pek])

  if (!pek) {
    return <Panel padding="md"><EmptyState message="PEK state unavailable" compact /></Panel>
  }

  return (
    <div className="space-y-4">
      {perfCards && (
        <Panel padding="md">
          <span className="text-2xs text-tertiary font-medium uppercase tracking-wider block mb-2">Performance State</span>
          <div className="grid grid-cols-3 lg:grid-cols-6 gap-2">
            {perfCards.map(c => (
              <StatCard key={c.label} label={c.label} value={c.value} variant="kpi" accent={c.accent} />
            ))}
          </div>
        </Panel>
      )}

      {velocityCards && (
        <Panel padding="md">
          <span className="text-2xs text-tertiary font-medium uppercase tracking-wider block mb-2">Velocity Sub-Metrics</span>
          <div className="grid grid-cols-3 lg:grid-cols-5 gap-2">
            {velocityCards.map(c => (
              <StatCard key={c.label} label={c.label} value={c.value} variant="kpi" accent={c.accent} />
            ))}
          </div>
        </Panel>
      )}

      {budgetCards && (
        <Panel padding="md">
          <span className="text-2xs text-tertiary font-medium uppercase tracking-wider block mb-2">Risk Budget</span>
          <div className="grid grid-cols-3 lg:grid-cols-6 gap-2">
            {budgetCards.map(c => (
              <StatCard key={c.label} label={c.label} value={c.value} variant="kpi" accent={c.accent} />
            ))}
          </div>
        </Panel>
      )}

      {snapCards && (
        <Panel padding="md">
          <span className="text-2xs text-tertiary font-medium uppercase tracking-wider block mb-2">Portfolio Snapshot</span>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
            {snapCards.map(c => (
              <StatCard key={c.label} label={c.label} value={c.value} sub={c.sub} variant="compact" accent={c.accent} />
            ))}
          </div>
        </Panel>
      )}
    </div>
  )
}
