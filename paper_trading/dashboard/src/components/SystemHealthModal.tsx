import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import { useMonitorAlerts } from '../hooks/useMonitorAlerts'
import { useSystemHealthModal } from '../hooks/useSystemHealthModal'
import HealthSnapshotCard from './monitor/HealthSnapshotCard'
import AlertFeed from './monitor/AlertFeed'
import GovernanceStatusGrid from './monitor/GovernanceStatusGrid'
import PerformancePanel from './monitor/PerformancePanel'
import { Skeleton } from './ui/Skeleton'
import Modal from './ui/Modal'

function avgHealth(health: { assets: Record<string, { health_score: number }> } | undefined): number | null {
  if (!health?.assets) return null
  const scores = Object.values(health.assets).map(a => a.health_score)
  return scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null
}

/** Full-system health modal with snapshot cards, alert feed, governance grid, and performance panel. */
export default function SystemHealthModal() {
  const { isOpen, close } = useSystemHealthModal()
  const { data: state } = useSystemSnapshot(systemSelectors.snapshot)
  const { data: health } = useSystemSnapshot(systemSelectors.health)
  const alerts = useMonitorAlerts()

  const portfolio = state?.portfolio
  const healthMean = avgHealth(health)
  const engine = state?.engine_status
  const openTrades = portfolio?.open_positions ?? 0

  const healthStatus =
    healthMean !== null
      ? healthMean >= 0.8
        ? 'healthy'
        : healthMean >= 0.5
        ? 'degraded'
        : 'critical'
      : undefined

  const governanceLayers = [
    {
      name: 'Exposure',
      status: ((portfolio?.average_validity_exposure ?? 1) < 0.3
        ? 'critical'
        : (portfolio?.average_validity_exposure ?? 1) < 0.7
        ? 'warning'
        : 'healthy') as 'critical' | 'warning' | 'healthy' | 'unknown',
      detail: `Avg exposure ${((portfolio?.average_validity_exposure ?? 0) * 100).toFixed(0)}%`,
      metric: portfolio?.deployment_cleared ? 'Cleared' : 'Pending',
    },
    {
      name: 'Drawdown Control',
      status: (healthMean === null
        ? 'unknown'
        : healthMean >= 0.8
        ? 'healthy'
        : healthMean >= 0.5
        ? 'warning'
        : 'critical') as 'critical' | 'warning' | 'healthy' | 'unknown',
      detail: healthMean !== null ? `Mean health ${(healthMean * 100).toFixed(0)}%` : 'N/A',
      metric: healthMean !== null ? `${health?.system_health?.n_healthy ?? 0} healthy` : '—',
    },
    {
      name: 'System Status',
      status: (engine?.market_closed
        ? 'warning'
        : engine?.initialized
        ? 'healthy'
        : 'critical') as 'critical' | 'warning' | 'healthy' | 'unknown',
      detail: engine?.market_closed
        ? 'Market closed'
        : engine?.initialized
        ? 'Active'
        : 'Not initialized',
      metric: engine?.last_update ? new Date(engine.last_update).toLocaleTimeString() : '—',
    },
    {
      name: 'Halt Monitor',
      status: (state?.halt_conditions
        ? state.halt_conditions.drawdown > 0.15
          ? 'critical'
          : state.halt_conditions.prob_drift > 0.3
          ? 'warning'
          : 'healthy'
        : 'unknown') as 'critical' | 'warning' | 'healthy' | 'unknown',
      detail: 'Auto-halt thresholds',
      metric: `DD ${((state?.halt_conditions?.drawdown ?? 0) * 100).toFixed(0)}% · PSI ${((state?.halt_conditions?.prob_drift ?? 0) * 100).toFixed(0)}%`,
    },
  ]

  const isPending = !state && !health

  // Commits 4.3+4.4 retrofit: replaced the bespoke modal chrome
  // (~95 LOC of: backdrop, escape, body-scroll-lock, focus, ARIA,
  // header X button) with the canonical <Modal> primitive. focus
  // trap is wired by default; modal title/description leak into
  // aria-labelledby / aria-describedby automatically.
  return (
    <Modal
      open={isOpen}
      onClose={close}
      title="System Health"
      description="Engine monitoring & governance overview"
      size="lg"
    >
      {isPending ? (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-16 rounded-lg" />
            ))}
          </div>
          <Skeleton className="h-32 rounded-lg" />
          <Skeleton className="h-24 rounded-lg" />
        </>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <HealthSnapshotCard
              title="Portfolio Health"
              value={healthMean !== null ? `${(healthMean * 100).toFixed(0)}%` : '—'}
              status={healthStatus}
            />
            <HealthSnapshotCard
              title="Active Trades"
              value={String(openTrades)}
              status="healthy"
            />
            <HealthSnapshotCard
              title="Total Value"
              value={
                portfolio
                  ? `$${portfolio.total_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                  : '—'
              }
              status={
                portfolio?.total_return && portfolio.total_return > 0
                  ? 'healthy'
                  : portfolio?.total_return && portfolio.total_return < 0
                  ? 'critical'
                  : undefined
              }
              trend={
                portfolio?.total_return && portfolio.total_return > 0
                  ? 'up'
                  : portfolio?.total_return && portfolio.total_return < 0
                  ? 'down'
                  : undefined
              }
              change={portfolio?.total_return ? `${portfolio.total_return.toFixed(2)}%` : undefined}
            />
            <HealthSnapshotCard
              title="Engine Status"
              value={engine?.market_closed ? 'CLOSED' : engine?.initialized ? 'RUNNING' : 'OFF'}
              status={
                engine?.initialized && !engine?.market_closed
                  ? 'healthy'
                  : engine?.initialized
                  ? 'degraded'
                  : 'critical'
              }
            />
          </div>

          <AlertFeed alerts={alerts} />
          <GovernanceStatusGrid layers={governanceLayers} />
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
                status:
                  healthMean !== null && healthMean >= 0.8
                    ? 'good'
                    : healthMean !== null && healthMean >= 0.5
                    ? 'warning'
                    : 'critical',
              },
              {
                label: 'Degraded / Critical',
                value: `${health?.system_health?.n_degraded ?? '—'} / ${
                  health?.system_health?.n_critical ?? '—'
                }`,
                status:
                  (health?.system_health?.n_critical ?? 0) > 0
                    ? 'critical'
                    : (health?.system_health?.n_degraded ?? 0) > 0
                    ? 'warning'
                    : 'good',
              },
            ]}
          />
        </>
      )}
    </Modal>
  )
}
