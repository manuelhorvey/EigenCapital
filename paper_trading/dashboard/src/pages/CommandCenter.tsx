import { memo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { useMonitorAlerts } from '../hooks/useMonitorAlerts'
import { useTradingState } from '../lib/trading-state/hook'
import SystemHealthSummary from '../components/SystemHealthSummary'
import EdgeHealthAlert from '../components/EdgeHealthAlert'
import LiveSharpeCard from '../components/LiveSharpeCard'
import OptimizerRecommendations from '../components/OptimizerRecommendations'
import HaltConditions from '../components/HaltConditions'
import EquityCurveSparkline from '../components/EquityCurveSparkline'
import AssetMiniGrid from '../components/AssetMiniGrid'
import TradingAssetRow from '../components/TradingAssetRow'
import Panel from '../components/ui/Panel'
import EntranceAnimator from '../components/ui/EntranceAnimator'
import EmptyState from '../components/ui/EmptyState'
import { Skeleton } from '../components/ui/Skeleton'
import { ArrowUpDown, AlertTriangle } from 'lucide-react'
import { formatTimeAgo } from '../utils/format'
import type { SortKey } from '../lib/trading-state/selectors'

// ── Quick Stats Row ──────────────────────────────────────────────────
//
// Terminal-precision row: one mono headline per metric, divided by
// hairline rules on the desktop layout. No card backgrounds, no
// icons, no shadows. Hairline rules define the cell boundary; values
// speak directly. The aesthetic risk is reading as a tabular
// accountancy report — which is the point: this row is a read-the-
// state channel, not a status card.

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
  const drawdownTone = drawdown >= 5 ? 'text-gov-red' : drawdown >= 1 ? 'text-gov-yellow' : 'text-secondary'

  // Mono row, one tabular cell per metric, divided by hairline rules.
  // This row is the operator's first read after the rail; it should fit
  // a 13" laptop without scrolling, give every value at the same
  // headline size, and recede into mono gray except for values that
  // are semantically coloured (GREEN / YELLOW / RED).
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 pb-3 text-2xs text-tertiary font-mono tabular-nums border-b border-default">
        <span>{lastUpdate ? `Snapshot ${formatTimeAgo(lastUpdate)}` : ''}</span>
        <span>{p.start_date ? `Since ${p.start_date}` : ''}</span>
        {criticalAlerts > 0 && (
          <span className="text-gov-red font-semibold">{criticalAlerts} critical alert{criticalAlerts > 1 ? 's' : ''}</span>
        )}
      </div>
      <dl className="grid grid-cols-2 lg:grid-cols-7 gap-y-3 lg:divide-x lg:divide-default">
        <Stat label="Portfolio Value" value={`$${(p.mtm_value ?? 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`} />
        <Stat label="Total Return" value={`${posReturn ? '+' : ''}${totalReturn.toFixed(2)}%`} tone={posReturn ? 'good' : 'bad'} />
        <Stat label="Realized P&L" value={`${posRealized ? '+' : ''}${(p.realized_return ?? 0).toFixed(2)}%`} tone={posRealized ? 'good' : 'bad'} />
        <Stat label="Drawdown" value={`-${Math.abs(drawdown).toFixed(2)}%`} tone={drawdownTone === 'text-secondary' ? undefined : drawdown >= 5 ? 'bad' : 'warn'} />
        <Stat label="Open / Closed" value={`${p.open_positions ?? 0} / ${p.closed_trades ?? 0}`} />
        <Stat label="Peak Value" value={peakValue != null ? `$${peakValue.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}` : '—'} />
        <Stat
          label={mt5Equity != null ? 'MT5 Equity' : 'Capital'}
          value={mt5Equity != null
            ? `$${mt5Equity.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
            : `$${(p.capital ?? 0).toLocaleString(undefined, { minimumFractionDigits: 0 })}`}
        />
      </dl>
    </div>
  )
})

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'good' | 'warn' | 'bad' }) {
  const cls = tone === 'good' ? 'text-gov-green'
    : tone === 'warn' ? 'text-gov-yellow'
    : tone === 'bad' ? 'text-gov-red'
    : 'text-primary'
  return (
    <div className="px-3 py-2 min-w-0">
      <dt className="text-2xs text-tertiary font-medium uppercase tracking-wider truncate">{label}</dt>
      <dd className={`text-base font-bold font-mono tabular-nums ${cls} mt-0.5 truncate`}>{value}</dd>
    </div>
  )
}

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
      {/* Emergency banner is rendered once at the AppShell level (above) */}
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
