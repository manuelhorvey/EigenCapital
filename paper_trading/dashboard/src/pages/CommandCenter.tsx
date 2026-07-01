import { memo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { useMonitorAlerts } from '../hooks/useMonitorAlerts'
import { useTradingState } from '../lib/trading-state/hook'
import SystemHealthSummary from '../components/SystemHealthSummary'
import ExitPhaseIndicator from '../components/ExitPhaseIndicator'
import EdgeHealthAlert from '../components/EdgeHealthAlert'
import LiveSharpeCard from '../components/LiveSharpeCard'
import OptimizerRecommendations from '../components/OptimizerRecommendations'
import HaltConditions from '../components/HaltConditions'
import EquityCurveSparkline from '../components/EquityCurveSparkline'
import EmergencyHaltBanner from '../components/EmergencyHaltBanner'
import AssetMiniGrid from '../components/AssetMiniGrid'
import Panel from '../components/ui/Panel'
import Badge from '../components/ui/Badge'
import EntranceAnimator from '../components/ui/EntranceAnimator'
import EmptyState from '../components/ui/EmptyState'
import { Skeleton } from '../components/ui/Skeleton'
import { TrendingUp, TrendingDown, DollarSign, Activity, ArrowDown, Goal, Banknote, ArrowUpDown, AlertTriangle } from 'lucide-react'
import { formatTimeAgo } from '../utils/format'
import type { SortKey } from '../lib/trading-state/selectors'

// ── Quick Stats Row ──────────────────────────────────────────────────

/** Local stat card that supports icon rendering inline with the label row. */
function QuickStatCard({ label, value, icon }: { label: string; value: string; icon: React.ReactNode }) {
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
  const { data: bundle } = useSystemSnapshot()
  const p = bundle?.snapshot?.portfolio
  const mt5Equity = bundle?.live?.mt5?.account?.portfolio_value
  const lastUpdate = p?.last_update ?? bundle?.snapshot?.engine_status?.last_update ?? bundle?.snapshot?.timestamp
  const alerts = useMonitorAlerts()
  const criticalAlerts = alerts.filter(a => a.severity === 'critical').length

  if (!p) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-7 gap-3">
        {Array.from({ length: 7 }).map((_, i) => <Skeleton key={i} className="h-20 rounded-lg" shimmer />)}
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
        <QuickStatCard
          label="Portfolio Value"
          value={`$${(p.mtm_value ?? 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
          icon={<DollarSign className="w-5 h-5 text-accent-emerald" strokeWidth={1.5} />}
        />
        <QuickStatCard
          label="Total Return"
          value={`${totalReturn.toFixed(2)}%`}
          icon={posReturn ? <TrendingUp className="w-5 h-5 text-gov-green" strokeWidth={1.5} /> : <TrendingDown className="w-5 h-5 text-gov-red" strokeWidth={1.5} />}
        />
        <QuickStatCard
          label="Realized P&L"
          value={`${posRealized ? '+' : ''}${(p.realized_return ?? 0).toFixed(2)}%`}
          icon={<TrendingUp className={`w-5 h-5 ${posRealized ? 'text-gov-green' : 'text-gov-red'}`} strokeWidth={1.5} />}
        />
        <QuickStatCard
          label="Drawdown"
          value={`${drawdown.toFixed(2)}%`}
          icon={<ArrowDown className="w-5 h-5 text-gov-red" strokeWidth={1.5} />}
        />
        <QuickStatCard
          label="Open / Closed"
          value={`${p.open_positions ?? 0} / ${p.closed_trades ?? 0}`}
          icon={<Activity className="w-5 h-5 text-accent-blue" strokeWidth={1.5} />}
        />
        <QuickStatCard
          label="Peak Value"
          value={peakValue != null ? `$${peakValue.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}` : '—'}
          icon={<Goal className="w-5 h-5 text-gov-yellow" strokeWidth={1.5} />}
        />
        {mt5Equity != null ? (
          <QuickStatCard
            label="MT5 Equity"
            value={`$${mt5Equity.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
            icon={<Banknote className="w-5 h-5 text-accent-blue" strokeWidth={1.5} />}
          />
        ) : (
          <QuickStatCard
            label="Capital"
            value={`$${(p.capital ?? 0).toLocaleString(undefined, { minimumFractionDigits: 0 })}`}
            icon={<Banknote className="w-5 h-5 text-tertiary" strokeWidth={1.5} />}
          />
        )}
      </div>
    </EntranceAnimator>
  )
})

// ── Trading Asset Row ──────────────────────────────────────────────

interface TradingAssetRowProps {
  asset: ReturnType<typeof useTradingState>['assetList'][number]
  onSelect?: (name: string) => void
}

const TradingAssetRow = memo(function TradingAssetRow({ asset, onSelect }: TradingAssetRowProps) {
  const pnlColor = asset.pnl_state.unrealized >= 0 ? '#22c55e' : '#ef4444'

  return (
    <button
      onClick={() => onSelect?.(asset.identity)}
      className="w-full flex items-center gap-3 py-2 px-2 rounded-lg hover:bg-panel/60 transition-colors border border-transparent hover:border-default group text-left"
    >
      {/* Asset name + direction */}
      <div className="flex items-center gap-2 w-28 shrink-0">
        <span className="text-xs font-semibold text-primary font-mono">{asset.identity}</span>
        {asset.direction && (
          <Badge
            variant={asset.direction === 'LONG' ? 'success' : 'error'}
            size="sm"
            icon={asset.direction === 'LONG' ? 'long' : 'short'}
          >
            {asset.direction === 'LONG' ? 'L' : 'S'}
          </Badge>
        )}
      </div>

      {/* PnL */}
      <div className="w-20 shrink-0 text-right">
        <span className="text-xs font-mono tabular-nums font-semibold" style={{ color: pnlColor }}>
          {asset.pnl_state.unrealized >= 0 ? '+' : ''}{asset.pnl_state.unrealized.toFixed(2)}
        </span>
      </div>

      {/* Exit phase */}
      <div className="w-36 shrink-0">
        <ExitPhaseIndicator
          phase={asset.exit_state.phase}
          slIsDynamic={asset.exit_state.sl_is_dynamic}
          peakMfeR={asset.exit_state.peak_mfe_r}
        />
      </div>

      {/* Risk level */}
      <div className="w-20 shrink-0">
        <Badge
          variant={asset.risk_state.level === 'HIGH' ? 'error' : asset.risk_state.level === 'MEDIUM' ? 'warning' : 'success'}
          size="sm"
          dot
        >
          {asset.risk_state.level}
        </Badge>
      </div>

      {/* Flags */}
      <div className="flex-1 flex items-center gap-1 min-w-0">
        {asset.flags.slice(0, 2).map((flag) => (
          <Badge key={flag} variant="neutral" size="sm">
            {flag.replace(/_/g, ' ')}
          </Badge>
        ))}
      </div>
    </button>
  )
})

// ── Asset List Panel ───────────────────────────────────────────────

interface AssetListPanelProps {
  onSelectAsset?: (name: string) => void
}

const AssetListPanel = memo(function AssetListPanel({ onSelectAsset }: AssetListPanelProps) {
  const { assetList, sortKey, sortAsc, setSortKey, toggleSortDirection, isLoading } = useTradingState()

  const sortOptions: { key: SortKey; label: string }[] = [
    { key: 'risk', label: 'Risk' },
    { key: 'name', label: 'Name' },
    { key: 'pnl', label: 'PnL' },
    { key: 'exit_phase', label: 'Exit' },
  ]

  return (
    <Panel padding="md">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-tertiary uppercase tracking-wider">Assets</span>
        <div className="flex items-center gap-1">
          {sortOptions.map((opt) => (
            <button
              key={opt.key}
              onClick={() => setSortKey(opt.key)}
              className={`text-[10px] px-1.5 py-0.5 rounded transition-colors ${
                sortKey === opt.key
                  ? 'bg-panel text-primary font-semibold'
                  : 'text-tertiary hover:text-secondary'
              }`}
            >
              {opt.label}
            </button>
          ))}
          <button
            onClick={toggleSortDirection}
            className="ml-1 p-0.5 rounded hover:bg-panel transition-colors"
            title={sortAsc ? 'Ascending' : 'Descending'}
          >
            <ArrowUpDown className="w-3 h-3 text-tertiary" strokeWidth={1.5} />
          </button>
          <span className="ml-2 text-[10px] text-tertiary">{assetList.length} assets</span>
        </div>
      </div>
      {assetList.length === 0 && !isLoading ? (
        <EmptyState message="No asset data available" compact />
      ) : (
        <div className="divide-y divide-border/50">
          {/* Column headers */}
          <div className="flex items-center gap-3 px-2 pb-1.5 text-[10px] text-tertiary font-medium uppercase tracking-wider">
            <span className="w-28">Asset</span>
            <span className="w-20 text-right">PnL</span>
            <span className="w-36">Exit Phase</span>
            <span className="w-20">Risk</span>
            <span className="flex-1">Flags</span>
          </div>
          {assetList.map(asset => (
            <TradingAssetRow key={asset.identity} asset={asset} onSelect={onSelectAsset} />
          ))}
        </div>
      )}
    </Panel>
  )
})

// ── Live Sharpe Panel ──────────────────────────────────────────────

const LiveSharpePanel = memo(function LiveSharpePanel() {
  return (
    <EntranceAnimator variant="fade-up" delay={120}>
      <div className="space-y-2">
        <span className="text-xs text-tertiary font-medium uppercase tracking-wider">Live Sharpe</span>
        <LiveSharpeCard />
      </div>
    </EntranceAnimator>
  )
})

// ── Main Page ──────────────────────────────────────────────────────

interface CommandCenterProps {
  onSelectAsset?: (name: string) => void
}

const CommandCenter = memo(function CommandCenter({ onSelectAsset }: CommandCenterProps) {
  const { portfolio } = useTradingState()
  const showEdgeWarning = portfolio?.alpha?.edge_trend === 'DECAYING'

  return (
    <div className="space-y-6 sm:space-y-8">
      {/* Emergency banner — highest priority */}
      <EmergencyHaltBanner />

      {/* System health — single source of truth */}
      <SystemHealthSummary />

      {/* Quick stats row */}
      <QuickStatsGrid />

      {/* Equity curve + edge health */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <Panel padding="md">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-medium text-tertiary uppercase tracking-wider">Equity Curve</span>
            </div>
            <div className="w-full">
              <EquityCurveSparkline height={80} />
            </div>
          </Panel>
        </div>
        <div>
          <EdgeHealthAlert />
        </div>
      </div>

      {/* Asset cards grid — open positions only */}
      <EntranceAnimator variant="fade-up" delay={45}>
        <AssetMiniGrid openOnly />
      </EntranceAnimator>

      {/* Asset list with sort controls — main trading view */}
      <EntranceAnimator variant="fade-up" delay={60}>
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs font-medium text-tertiary uppercase tracking-wider">Positions</span>
          {showEdgeWarning && (
            <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-gov-yellow/10 border border-gov-yellow/20 text-[10px] text-gov-yellow">
              <AlertTriangle className="w-3 h-3" strokeWidth={2} />
              Edge decaying — monitor reversals
            </div>
          )}
        </div>
        <AssetListPanel onSelectAsset={onSelectAsset} />
      </EntranceAnimator>

      {/* Risk signals + optimizer */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <EntranceAnimator variant="fade-up" delay={120}>
          <div className="space-y-2">
            <span className="text-xs text-tertiary font-medium uppercase tracking-wider">Risk Signals</span>
            <HaltConditions />
          </div>
        </EntranceAnimator>
        <EntranceAnimator variant="fade-up" delay={180}>
          <div className="space-y-2">
            <span className="text-xs text-tertiary font-medium uppercase tracking-wider">Optimizer</span>
            <OptimizerRecommendations />
          </div>
        </EntranceAnimator>
      </div>

      {/* Live sharpe */}
      <LiveSharpePanel />
    </div>
  )
})

export default CommandCenter
