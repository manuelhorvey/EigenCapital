import { memo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import { useMonitorAlerts } from '../hooks/useMonitorAlerts'
import PortfolioSummary from '../components/PortfolioSummary'
import HaltConditions from '../components/HaltConditions'
import Panel from '../components/ui/Panel'
import EntranceAnimator from '../components/ui/EntranceAnimator'
import { Skeleton } from '../components/ui/Skeleton'
import { TrendingUp, TrendingDown, DollarSign, Activity } from 'lucide-react'

function StatCard({ label, value, icon }: { label: string; value: string; icon: React.ReactNode }) {
  return (
    <Panel className="flex items-center gap-3 p-4 hover:border-strong transition-all duration-200 group" gradient>
      <div className="w-10 h-10 rounded-lg bg-panel flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform duration-200">
        {icon}
      </div>
      <div className="min-w-0">
        <p className="text-2xs text-tertiary font-medium uppercase tracking-wider">{label}</p>
        <p className="text-sm font-semibold text-primary font-mono tabular-nums mt-0.5">{value}</p>
      </div>
    </Panel>
  )
}

const QuickStatsGrid = memo(function QuickStatsGrid() {
  const { data: portfolio } = useSystemSnapshot(systemSelectors.portfolio)
  const alerts = useMonitorAlerts()
  const criticalAlerts = alerts.filter(a => a.severity === 'critical').length

  if (!portfolio) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-20 rounded-lg" shimmer />)}
      </div>
    )
  }

  const pnl = portfolio.mtm_value - portfolio.capital
  const pnlPct = portfolio.capital > 0 ? (pnl / portfolio.capital) * 100 : 0

  return (
    <EntranceAnimator>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          label="Portfolio Value"
          value={`$${portfolio.mtm_value.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
          icon={<DollarSign className="w-5 h-5 text-accent-emerald" strokeWidth={1.5} />}
        />
        <StatCard
          label="Total Return"
          value={`${portfolio.total_return.toFixed(2)}%`}
          icon={pnlPct >= 0 ? <TrendingUp className="w-5 h-5 text-gov-green" strokeWidth={1.5} /> : <TrendingDown className="w-5 h-5 text-gov-red" strokeWidth={1.5} />}
        />
        <StatCard
          label="Open Positions"
          value={String(portfolio.open_positions)}
          icon={<Activity className="w-5 h-5 text-accent-blue" strokeWidth={1.5} />}
        />
        <StatCard
          label="Alerts"
          value={String(criticalAlerts)}
          icon={<TrendingUp className="w-5 h-5 text-gov-yellow" strokeWidth={1.5} />}
        />
      </div>
    </EntranceAnimator>
  )
})

const PortfolioSnapshotPanel = memo(function PortfolioSnapshotPanel() {
  return (
    <EntranceAnimator variant="fade-up" delay={60}>
      <PortfolioSummary />
    </EntranceAnimator>
  )
})

const RiskSignalPanel = memo(function RiskSignalPanel() {
  return (
    <EntranceAnimator variant="fade-up" delay={120}>
      <HaltConditions />
    </EntranceAnimator>
  )
})

const DashboardOverview = memo(function DashboardOverview() {
  return (
    <div className="space-y-6 sm:space-y-8">
      <QuickStatsGrid />
      <PortfolioSnapshotPanel />
      <RiskSignalPanel />
    </div>
  )
})

export default DashboardOverview
