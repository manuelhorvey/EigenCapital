import { usePortfolioState } from '../../hooks/usePortfolioState'
import { useHealthScores } from '../../hooks/useHealthScores'
import { useMonitorAlerts } from '../../hooks/useMonitorAlerts'
import HealthSnapshotCard from './HealthSnapshotCard'
import AlertFeed from './AlertFeed'
import GovernanceStatusGrid from './GovernanceStatusGrid'
import PerformancePanel from './PerformancePanel'
import Panel from '../ui/Panel'
import SectionHeader from '../ui/SectionHeader'
import { Skeleton } from '../ui/Skeleton'
import { Activity, DollarSign, TrendingUp, Zap } from 'lucide-react'

function avgHealth(health: { assets: Record<string, { health_score: number }> } | undefined): number | null {
  if (!health?.assets) return null
  const scores = Object.values(health.assets).map(a => a.health_score)
  return scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null
}

export default function MonitoringDashboard() {
  const { data: state } = usePortfolioState()
  const { data: health } = useHealthScores()
  const alerts = useMonitorAlerts()

  const isPending = !state && !health

  if (isPending) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))}
        </div>
        <Skeleton className="h-32 rounded-lg" />
        <Skeleton className="h-24 rounded-lg" />
      </div>
    )
  }

  const portfolio = state?.portfolio
  const healthMean = avgHealth(health)
  const engine = state?.engine_status
  const openTrades = portfolio?.open_positions ?? 0

  const healthStatus = healthMean !== null
    ? (healthMean >= 0.8 ? 'healthy' : healthMean >= 0.5 ? 'degraded' : 'critical')
    : undefined

  // Build governance layers from health & halt data
  const governanceLayers = [
    {
      name: 'Exposure',
      status: (portfolio?.average_validity_exposure ?? 0) > 0.95 ? 'critical' as const
        : (portfolio?.average_validity_exposure ?? 0) > 0.9 ? 'warning' as const
        : 'healthy' as const,
      detail: `Avg exposure ${((portfolio?.average_validity_exposure ?? 0) * 100).toFixed(0)}%`,
      metric: portfolio?.deployment_cleared ? 'Cleared' : 'Pending',
    },
    {
      name: 'Drawdown Control',
      status: healthMean !== null && healthMean >= 0.8 ? 'healthy' as const
        : healthMean !== null && healthMean >= 0.5 ? 'warning' as const
        : 'critical' as const,
      detail: healthMean !== null ? `Mean health ${(healthMean * 100).toFixed(0)}%` : 'N/A',
      metric: `${health?.system_health.n_healthy ?? 0} healthy`,
    },
    {
      name: 'System Status',
      status: engine?.market_closed ? 'warning' as const
        : engine?.initialized ? 'healthy' as const
        : 'critical' as const,
      detail: engine?.market_closed ? 'Market closed' : engine?.initialized ? 'Active' : 'Not initialized',
      metric: engine?.last_update ? new Date(engine.last_update).toLocaleTimeString() : '—',
    },
    {
      name: 'Halt Monitor',
      status: state?.halt_conditions ? (
        state.halt_conditions.drawdown > 0.15 ? 'critical' as const
        : state.halt_conditions.prob_drift > 0.3 ? 'warning' as const
        : 'healthy' as const
      ) : 'unknown' as const,
      detail: 'Auto-halt thresholds',
      metric: `DD ${((state?.halt_conditions?.drawdown ?? 0) * 100).toFixed(0)}% · PSI ${((state?.halt_conditions?.prob_drift ?? 0) * 100).toFixed(0)}%`,
    },
  ]

  return (
    <div className="space-y-4">
      {/* Layer 1: Health Snapshot */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <HealthSnapshotCard
          title="Portfolio Health"
          value={healthMean !== null ? `${(healthMean * 100).toFixed(0)}%` : '—'}
          status={healthStatus}
        />
        <HealthSnapshotCard
          title="Active Trades"
          value={String(openTrades)}
          status={openTrades > 0 ? 'healthy' : 'healthy'}
          icon={<Activity className="w-3 h-3" strokeWidth={2} />}
        />
        <HealthSnapshotCard
          title="Total Value"
          value={portfolio ? `$${portfolio.total_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '—'}
          status={portfolio?.total_return && portfolio.total_return > 0 ? 'healthy' : portfolio?.total_return && portfolio.total_return < 0 ? 'critical' : undefined}
          trend={portfolio?.total_return && portfolio.total_return > 0 ? 'up' : portfolio?.total_return && portfolio.total_return < 0 ? 'down' : undefined}
          change={portfolio?.total_return ? `${portfolio.total_return.toFixed(2)}%` : undefined}
          icon={<DollarSign className="w-3 h-3" strokeWidth={2} />}
        />
        <HealthSnapshotCard
          title="Engine Status"
          value={engine?.market_closed ? 'CLOSED' : engine?.initialized ? 'RUNNING' : 'OFF'}
          status={engine?.initialized && !engine?.market_closed ? 'healthy' : engine?.initialized ? 'degraded' : 'critical'}
          icon={<Zap className="w-3 h-3" strokeWidth={2} />}
        />
      </div>

      {/* Layer 2: Alert Feed */}
      <AlertFeed alerts={alerts} />

      {/* Layer 3: Governance Status */}
      <GovernanceStatusGrid layers={governanceLayers} />

      {/* Layer 4: Performance */}
      <PerformancePanel
        metrics={[
          {
            label: 'Runtime',
            value: portfolio ? `${portfolio.runtime_hours.toFixed(0)}h` : '—',
            status: 'good',
          },
          {
            label: 'Days Active',
            value: portfolio ? `${portfolio.days_running}d` : '—',
            status: 'good',
          },
          {
            label: 'Health Avg',
            value: healthMean !== null ? `${(healthMean * 100).toFixed(1)}%` : '—',
            status: healthMean !== null && healthMean >= 0.8 ? 'good' : healthMean !== null && healthMean >= 0.5 ? 'warning' : 'critical',
          },
          {
            label: 'Degraded / Critical',
            value: `${health?.system_health.n_degraded ?? '—'} / ${health?.system_health.n_critical ?? '—'}`,
            status: (health?.system_health.n_critical ?? 0) > 0 ? 'critical'
              : (health?.system_health.n_degraded ?? 0) > 0 ? 'warning'
              : 'good',
          },
        ]}
      />
    </div>
  )
}
