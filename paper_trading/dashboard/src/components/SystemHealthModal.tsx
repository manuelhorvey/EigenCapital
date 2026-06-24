import { useEffect, useRef } from 'react'
import { X, Activity, DollarSign, TrendingUp, Zap } from 'lucide-react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import { useMonitorAlerts } from '../hooks/useMonitorAlerts'
import { useSystemHealthModal } from '../hooks/useSystemHealthModal'
import HealthSnapshotCard from './monitor/HealthSnapshotCard'
import AlertFeed from './monitor/AlertFeed'
import GovernanceStatusGrid from './monitor/GovernanceStatusGrid'
import PerformancePanel from './monitor/PerformancePanel'
import { Skeleton } from './ui/Skeleton'

function avgHealth(health: { assets: Record<string, { health_score: number }> } | undefined): number | null {
  if (!health?.assets) return null
  const scores = Object.values(health.assets).map(a => a.health_score)
  return scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null
}

export default function SystemHealthModal() {
  const { isOpen, close } = useSystemHealthModal()
  const { data: state } = useSystemSnapshot(systemSelectors.snapshot)
  const { data: health } = useSystemSnapshot(systemSelectors.health)
  const alerts = useMonitorAlerts()
  const modalRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!isOpen) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [isOpen, close])

  useEffect(() => {
    if (!isOpen) return
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [isOpen])

  if (!isOpen) return null

  const portfolio = state?.portfolio
  const healthMean = avgHealth(health)
  const engine = state?.engine_status
  const openTrades = portfolio?.open_positions ?? 0

  const healthStatus = healthMean !== null
    ? (healthMean >= 0.8 ? 'healthy' : healthMean >= 0.5 ? 'degraded' : 'critical')
    : undefined

  const governanceLayers = [
    {
      name: 'Exposure',
      status: (portfolio?.average_validity_exposure ?? 1) < 0.3 ? 'critical' as const
        : (portfolio?.average_validity_exposure ?? 1) < 0.7 ? 'warning' as const
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
      metric: `${health?.system_health?.n_healthy ?? 0} healthy`,
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

  const isPending = !state && !health

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-8 sm:pt-16 px-4">
      <div className="fixed inset-0 bg-black/60" onClick={close} aria-hidden="true" />
      <div ref={modalRef} className="relative w-full max-w-2xl bg-app border border-default rounded-xl shadow-2xl animate-fade-in max-h-[85vh] flex flex-col" role="dialog" aria-modal="true" aria-label="System Health">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-default shrink-0">
          <div>
            <h2 className="text-sm font-semibold text-primary flex items-center gap-2">
              <Activity className="w-4 h-4 text-accent-emerald" strokeWidth={1.5} />
              System Health
            </h2>
            <p className="text-2xs text-tertiary font-mono mt-0.5">Engine monitoring & governance overview</p>
          </div>
          <button
            onClick={close}
            className="p-1.5 rounded-md hover:bg-panel border border-transparent hover:border-default transition-colors"
          >
            <X className="w-3.5 h-3.5 text-tertiary" strokeWidth={2} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
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
                    status: healthMean !== null && healthMean >= 0.8 ? 'good' : healthMean !== null && healthMean >= 0.5 ? 'warning' : 'critical',
                  },
                  {
                    label: 'Degraded / Critical',
                    value: `${health?.system_health?.n_degraded ?? '—'} / ${health?.system_health?.n_critical ?? '—'}`,
                    status: (health?.system_health?.n_critical ?? 0) > 0 ? 'critical'
                      : (health?.system_health?.n_degraded ?? 0) > 0 ? 'warning'
                      : 'good',
                  },
                ]}
              />
            </>
          )}
        </div>
      </div>
    </div>
  )
}
