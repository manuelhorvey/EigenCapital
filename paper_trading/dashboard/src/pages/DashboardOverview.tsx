import { memo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import { useMonitorAlerts } from '../hooks/useMonitorAlerts'
import AssetMiniGrid from '../components/AssetMiniGrid'
import EquityChart from '../components/EquityChart'
import AssetsHealthPanel from '../components/AssetsHealthPanel'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/ui/StatCard'
import EntranceAnimator from '../components/ui/EntranceAnimator'
import { Skeleton } from '../components/ui/Skeleton'
import { TrendingUp, TrendingDown, DollarSign, Activity, ArrowDown, Goal, Banknote } from 'lucide-react'
import { formatTimeAgo } from '../utils/format'
import { useEngineHealth } from '../hooks/useEngineHealth'

const QuickStatsGrid = memo(function QuickStatsGrid() {
  const { data: bundle } = useSystemSnapshot()
  const p = bundle?.snapshot?.portfolio
  const mt5Equity = bundle?.live?.mt5?.account?.portfolio_value
  const lastUpdate = p?.last_update ?? bundle?.snapshot?.engine_status?.last_update ?? bundle?.snapshot?.timestamp
  const alerts = useMonitorAlerts()
  const criticalAlerts = alerts.filter(a => a.severity === 'critical').length

  if (!p) {
    return (
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 lg:grid-cols-7 gap-3">
          {Array.from({ length: 7 }).map((_, i) => <Skeleton key={i} className="h-20 rounded-lg" shimmer />)}
        </div>
      </div>
    )
  }

  const totalReturn = p.total_return ?? 0
  const drawdown = p.portfolio_drawdown ?? 0
  const peakValue = p.portfolio_peak_value
  const posReturn = totalReturn >= 0
  const posRealized = (p.realized_return ?? 0) >= 0

  return (
    <EntranceAnimator>
      <div className="flex flex-wrap items-center justify-between gap-2 pb-2 text-2xs text-tertiary font-mono tabular-nums">
        <span>{lastUpdate ? `Snapshot ${formatTimeAgo(lastUpdate)}` : ''}</span>
        <span>{p.start_date ? `Since ${p.start_date}` : ''}</span>
        {criticalAlerts > 0 && (
          <span className="text-gov-red font-semibold">{criticalAlerts} critical alert{criticalAlerts > 1 ? 's' : ''}</span>
        )}
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-7 gap-3">
        <StatCard
          size="sm"
          label="Portfolio Value"
          value={`$${(p.mtm_value ?? 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
          icon={<DollarSign className="w-5 h-5 text-accent-emerald" strokeWidth={1.5} />}
        />
        <StatCard
          size="sm"
          label="Total Return"
          value={`${totalReturn.toFixed(2)}%`}
          icon={posReturn ? <TrendingUp className="w-5 h-5 text-gov-green" strokeWidth={1.5} /> : <TrendingDown className="w-5 h-5 text-gov-red" strokeWidth={1.5} />}
        />
        <StatCard
          size="sm"
          label="Realized P&L"
          value={`${posRealized ? '+' : ''}${(p.realized_return ?? 0).toFixed(2)}%`}
          icon={<TrendingUp className={`w-5 h-5 ${posRealized ? 'text-gov-green' : 'text-gov-red'}`} strokeWidth={1.5} />}
        />
        <StatCard
          size="sm"
          label="Drawdown"
          value={`${drawdown.toFixed(2)}%`}
          icon={<ArrowDown className="w-5 h-5 text-gov-red" strokeWidth={1.5} />}
        />
        <StatCard
          size="sm"
          label="Open / Closed"
          value={`${p.open_positions ?? 0} / ${p.closed_trades ?? 0}`}
          icon={<Activity className="w-5 h-5 text-accent-blue" strokeWidth={1.5} />}
        />
        <StatCard
          size="sm"
          label="Peak Value"
          value={peakValue != null ? `$${peakValue.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}` : '—'}
          icon={<Goal className="w-5 h-5 text-gov-yellow" strokeWidth={1.5} />}
        />
        {mt5Equity != null ? (
          <StatCard
            size="sm"
            label="MT5 Equity"
            value={`$${mt5Equity.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
            icon={<Banknote className="w-5 h-5 text-accent-blue" strokeWidth={1.5} />}
          />
        ) : (
          <StatCard
            size="sm"
            label="Capital"
            value={`$${(p.capital ?? 0).toLocaleString(undefined, { minimumFractionDigits: 0 })}`}
            icon={<Banknote className="w-5 h-5 text-tertiary" strokeWidth={1.5} />}
          />
        )}
      </div>
    </EntranceAnimator>
  )
})

const PekStatusBar = memo(function PekStatusBar() {
  const { data: bundle } = useSystemSnapshot()
  const portfolio = bundle?.snapshot?.portfolio
  const adm = portfolio?.admission
  const ps = portfolio?.pek?.performance_state

  if (!adm && !ps) return null

  const admittedPct = adm && adm.n_intents > 0 ? (adm.n_admitted / adm.n_intents * 100).toFixed(0) : null
  const velocityVal = typeof ps?.velocity_scalar === 'number' ? ps.velocity_scalar.toFixed(3) : null
  const compositeVal = typeof ps?.composite_scalar === 'number' ? ps.composite_scalar.toFixed(3) : null
  const winRateVal = typeof ps?.win_rate_20 === 'number' ? (ps.win_rate_20 * 100).toFixed(0) : null
  const budgetVal = typeof adm?.budget_notional === 'number' ? adm.budget_notional.toLocaleString() : null

  return (
    <div className="flex flex-wrap items-center gap-4 px-1 py-2 text-2xs text-tertiary font-mono border-b border-border">
      {adm && admittedPct != null && (
        <span>
          PEK admission: <span className="font-semibold text-primary">{adm.n_admitted}/{adm.n_intents}</span> ({admittedPct}%)
        </span>
      )}
      {velocityVal != null && (
        <span>
          Velocity: <span className="font-semibold text-primary">{velocityVal}</span>
        </span>
      )}
      {budgetVal != null && (
        <span>
          Budget notional: <span className="font-semibold text-primary">${budgetVal}</span>
        </span>
      )}
      {compositeVal != null && (
        <span>
          Composite: <span className="font-semibold text-primary">{compositeVal}</span>
        </span>
      )}
      {winRateVal != null && (
        <span>
          Win rate (20): <span className="font-semibold text-primary">{winRateVal}%</span>
        </span>
      )}
    </div>
  )
})

const DashboardHeaderStatus = memo(function DashboardHeaderStatus() {
  const health = useEngineHealth()
  const { data: engine } = useSystemSnapshot(systemSelectors.engineStatus)
  const engineAlive = health.data?.engine_alive ?? false
  const closed = engine?.market_closed
  const label = health.isError
    ? 'Disconnected'
    : health.isLoading
      ? '…'
      : closed
        ? 'Market closed'
        : engineAlive
          ? 'Engine live'
          : 'Stale'
  const dot = health.isError ? 'bg-gov-red' : engineAlive && !closed ? 'bg-gov-green' : closed ? 'bg-gov-yellow' : 'bg-gov-red'
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-default bg-panel/50 text-[10px] font-mono text-tertiary">
      <span className={`relative inline-flex w-1.5 h-1.5 rounded-full ${dot}`} />
      {label}
    </span>
  )
})

const DashboardOverview = memo(function DashboardOverview() {
  const { data: engine } = useSystemSnapshot(systemSelectors.engineStatus)
  const alerts = useMonitorAlerts()
  const criticalAlerts = alerts.filter(a => a.severity === 'critical').length

  return (
    <div className="space-y-6 sm:space-y-8">
      <PageHeader
        title="Overview"
        description="System health, portfolio summary, and live asset signals at a glance."
        crumbs={[{ label: 'Overview' }]}
        status={
          <>
            <DashboardHeaderStatus />
            {criticalAlerts > 0 && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-gov-red/25 bg-gov-red-muted text-gov-red text-[10px] font-mono font-semibold">
                {criticalAlerts} critical alert{criticalAlerts > 1 ? 's' : ''}
              </span>
            )}
            {engine?.last_update && (
              <span className="hidden sm:inline-flex items-center px-2.5 py-1 rounded-md border border-default bg-panel/50 text-[10px] font-mono text-tertiary">
                {formatTimeAgo(engine.last_update)}
              </span>
            )}
          </>
        }
      />
      <QuickStatsGrid />
      <PekStatusBar />
      <EntranceAnimator variant="fade-up" delay={30}>
        <EquityChart compact />
      </EntranceAnimator>
      <AssetsHealthPanel />
      <EntranceAnimator variant="fade-up" delay={60}>
        <AssetMiniGrid />
      </EntranceAnimator>
    </div>
  )
})

export default DashboardOverview
