import { useMemo } from 'react'
import PageHeader from '../components/PageHeader'
import Section from '../components/ui/Section'
import AlertFeed from '../components/monitor/AlertFeed'
import HealthSnapshotCard from '../components/monitor/HealthSnapshotCard'
import GovernanceStatusGrid from '../components/monitor/GovernanceStatusGrid'
import PerformancePanel from '../components/monitor/PerformancePanel'
import { useMonitorAlerts } from '../hooks/useMonitorAlerts'
import { useGovernanceRadar } from '../hooks/useGovernanceRadar'
import { useEngineHealth } from '../hooks/useEngineHealth'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import { ShieldCheck, Activity, Cpu } from 'lucide-react'

type Status = 'healthy' | 'degraded' | 'critical'

function govStatus(v: number): Status {
  if (v >= 0.8) return 'healthy'
  if (v >= 0.5) return 'degraded'
  return 'critical'
}

function layerStatus(v: number): 'healthy' | 'warning' | 'critical' {
  if (v >= 0.8) return 'healthy'
  if (v >= 0.5) return 'warning'
  return 'critical'
}

function SystemHealthCards() {
  const health = useEngineHealth()
  const { data: engine } = useSystemSnapshot(systemSelectors.engineStatus)
  const running = !health.isError && !!health.data?.engine_alive
  const closed = engine?.market_closed

  const cards = [
    {
      title: 'Engine',
      value: running ? 'RUNNING' : 'OFFLINE',
      status: (running ? 'healthy' : 'critical') as Status,
      icon: <Cpu className="h-3 w-3" strokeWidth={2} />,
    },
    {
      title: 'Market',
      value: closed ? 'CLOSED' : 'OPEN',
      status: (closed ? 'degraded' : 'healthy') as Status,
      icon: <Activity className="h-3 w-3" strokeWidth={2} />,
    },
    {
      title: 'State file',
      value: health.data?.state_exists ? `${health.data.state_file_age_s}s` : 'MISSING',
      status: (health.data?.state_exists ? 'healthy' : 'critical') as Status,
      icon: <Cpu className="h-3 w-3" strokeWidth={2} />,
    },
  ]

  return (
    <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
      {cards.map(c => <HealthSnapshotCard key={c.title} title={c.title} value={c.value} status={c.status} icon={c.icon} />)}
    </div>
  )
}

function PortfolioHealthCards() {
  const { data: health } = useSystemSnapshot((b) => b.live?.health)

  const sys = health?.system_health
  const scores = health?.assets ? Object.values(health.assets).map(h => h.health_score) : []
  const avg = sys?.mean_health_score ?? (scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0)

  const cards = [
    {
      title: 'Avg Health',
      value: scores.length ? `${(avg * 100).toFixed(0)}%` : '—',
      status: govStatus(avg),
      icon: <ShieldCheck className="h-3 w-3" strokeWidth={2} />,
    },
    {
      title: 'Assets',
      value: sys?.n_assets != null ? String(sys.n_assets) : '—',
      status: 'healthy' as Status,
      icon: <Activity className="h-3 w-3" strokeWidth={2} />,
    },
    {
      title: 'Healthy',
      value: sys?.n_healthy != null ? `${sys.n_healthy}/${sys.n_assets ?? '?'}` : '—',
      status: 'healthy' as Status,
      icon: <ShieldCheck className="h-3 w-3" strokeWidth={2} />,
    },
  ]

  return (
    <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
      {cards.map(c => <HealthSnapshotCard key={c.title} title={c.title} value={c.value} status={c.status} icon={c.icon} />)}
    </div>
  )
}

export default function MonitorWorkspace() {
  const alerts = useMonitorAlerts()
  const { axes, bottlenecks, avgValidityImpact } = useGovernanceRadar()

  const layers = useMemo(
    () => axes.map(a => ({
      name: a.label,
      status: layerStatus(a.value),
      detail: a.description,
      metric: `${(a.value * 100).toFixed(0)}%`,
    })),
    [axes],
  )

  return (
    <div className="space-y-6 sm:space-y-8">
      <PageHeader
        title="Monitor"
        description="System liveness, active alerts, governance health ratings, and lead indicators."
        crumbs={[{ label: 'Monitor' }]}
      />
      <Section id="system" errorTitle="System Health">
        <SystemHealthCards />
        <div className="mt-3">
          <PortfolioHealthCards />
        </div>
      </Section>
      <Section id="alerts" errorTitle="Active Alerts">
        <AlertFeed alerts={alerts} />
      </Section>
      <Section id="governance" errorTitle="Governance Health">
        <GovernanceStatusGrid layers={layers} />
      </Section>
      <Section id="lead" errorTitle="Lead Indicators">
        <PerformancePanel
          metrics={[
            { label: 'Validity Impact', value: `${(avgValidityImpact * 100).toFixed(1)}%`, status: avgValidityImpact >= -0.05 ? 'good' : 'critical' },
            { label: 'Active Constraints', value: String(bottlenecks.length), status: bottlenecks.length > 0 ? 'warning' : 'good' },
          ]}
        />
      </Section>
    </div>
  )
}