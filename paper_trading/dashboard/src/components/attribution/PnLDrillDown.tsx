import { useState, useMemo, useCallback } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  AreaChart, Area, CartesianGrid, ReferenceLine, Cell,
} from 'recharts'
import {
  TrendingUp, TrendingDown, DollarSign, Target, Search,
  ArrowUpDown, Download, BarChart3,
} from 'lucide-react'
import { useAttributionTrades, type TradeAttributionRecord } from '../../hooks/useAttributionTrades'
import TradeInspectorModal from '../trades/TradeInspectorModal'
import ExpandableSection from '../ui/ExpandableSection'
import Panel from '../ui/Panel'
import SectionHeader from '../ui/SectionHeader'
import { EntranceAnimator } from '../ui'
import { SECTION_SPACING, GRID_GAP } from '../../design/grid'
import {
  axisTick, chartMargin, tooltipStyle,
  tooltipLabelStyle, cartesianGridProps, chartCursor,
  ChartGradientDefs, getGradientFill,
} from '../ui/chartTheme'

// ── Types ──────────────────────────────────────────────────────────

type TimeAggregation = 'daily' | 'weekly' | 'monthly'
type PnLSortKey = 'pnl' | 'n_trades' | 'win_rate' | 'avg_r'

interface AssetPnLRow {
  asset: string
  pnl: number
  n_trades: number
  win_rate: number
  avg_r: number
  return_pct: number
}

interface TimePnLPoint {
  period: string
  pnl: number
  cumulative: number
  n_trades: number
}

// ── Helpers ────────────────────────────────────────────────────────

function formatPnl(v: number): string {
  const abs = Math.abs(v)
  const formatted = abs >= 1000 ? `${(abs / 1000).toFixed(1)}k` : abs.toFixed(2)
  return v >= 0 ? `+$${formatted}` : `-$${formatted}`
}

function formatPct(v: number): string {
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`
}

function dateToPeriod(ts: string, agg: TimeAggregation): string {
  const d = new Date(ts)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  if (agg === 'daily') return `${y}-${m}-${day}`
  if (agg === 'weekly') {
    const start = new Date(d)
    start.setDate(d.getDate() - d.getDay())
    return `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}-${String(start.getDate()).padStart(2, '0')}`
  }
  return `${y}-${m}`
}

function aggregateTrades(
  trades: TradeAttributionRecord[],
  agg: TimeAggregation,
): { timeSeries: TimePnLPoint[]; byAsset: AssetPnLRow[]; totalPnL: number; totalTrades: number } {
  // Time-series aggregation
  const periodMap = new Map<string, number[]>()
  for (const t of trades) {
    const period = dateToPeriod(t.exit_date || t.entry_date, agg)
    const existing = periodMap.get(period) ?? []
    existing.push(t.realized_pnl)
    periodMap.set(period, existing)
  }

  const sortedPeriods = [...periodMap.keys()].sort()
  let cumulative = 0
  const timeSeries: TimePnLPoint[] = sortedPeriods.map(p => {
    const pnls = periodMap.get(p)!
    const periodPnL = pnls.reduce((a, b) => a + b, 0)
    cumulative += periodPnL
    return {
      period: p,
      pnl: periodPnL,
      cumulative,
      n_trades: pnls.length,
    }
  })

  // Per-asset aggregation
  const assetMap = new Map<string, { pnls: number[]; rvals: number[]; wins: number }>()
  for (const t of trades) {
    const existing = assetMap.get(t.asset) ?? { pnls: [], rvals: [], wins: 0 }
    existing.pnls.push(t.realized_pnl)
    existing.rvals.push(t.exit_realized_r)
    if (t.realized_pnl > 0) existing.wins++
    assetMap.set(t.asset, existing)
  }

  const byAsset: AssetPnLRow[] = [...assetMap.entries()]
    .map(([asset, d]) => ({
      asset,
      pnl: d.pnls.reduce((a, b) => a + b, 0),
      n_trades: d.pnls.length,
      win_rate: d.pnls.length > 0 ? d.wins / d.pnls.length : 0,
      avg_r: d.rvals.length > 0 ? d.rvals.reduce((a, b) => a + b, 0) / d.rvals.length : 0,
      return_pct: 0, // calculated below if we have equity data
    }))
    .sort((a, b) => b.pnl - a.pnl)

  const totalPnL = trades.reduce((a, t) => a + t.realized_pnl, 0)
  const totalTrades = trades.length

  return { timeSeries, byAsset, totalPnL, totalTrades }
}

function getPnLColor(v: number): string {
  return v >= 0 ? 'var(--color-signal-long)' : 'var(--color-signal-short)'
}

import ChartDataTable from '../ui/ChartDataTable'
import { memo, type ReactNode } from 'react'

// ── Components ─────────────────────────────────────────────────────

const KpiCard = memo(function KpiCard({
  label, value, color, icon, sub,
}: {
  label: string; value: string; color: string; icon: ReactNode; sub?: string
}) {
  return (
    <Panel padding="md" className="flex items-center gap-3">
      <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-surface border border-default shrink-0" style={{ color }}>
        {icon}
      </div>
      <div className="min-w-0">
        <p className="text-[10px] text-tertiary font-medium uppercase tracking-wider">{label}</p>
        <p className="text-sm font-bold font-mono tabular-nums truncate" style={{ color }}>{value}</p>
        {sub && <p className="text-[10px] text-tertiary font-mono mt-px">{sub}</p>}
      </div>
    </Panel>
  )
})

function AssetPnLTable({
  data,
  onExport,
}: {
  data: AssetPnLRow[]
  onExport: () => void
}) {
  const [sortKey, setSortKey] = useState<PnLSortKey>('pnl')
  const [sortAsc, setSortAsc] = useState(false)

  const sorted = useMemo(() => {
    const sorted = [...data].sort((a, b) => {
      const cmp = a[sortKey] - b[sortKey]
      return sortAsc ? cmp : -cmp
    })
    return sorted
  }, [data, sortKey, sortAsc])

  const maxPnL = Math.max(...data.map(d => Math.abs(d.pnl)), 1)

  const SortButton = ({ k, label }: { k: PnLSortKey; label: string }) => (
    <button
      onClick={() => {
        if (sortKey === k) setSortAsc(!sortAsc)
        else { setSortKey(k); setSortAsc(false) }
      }}
      className={`text-[10px] font-medium uppercase tracking-wider flex items-center gap-1 transition-colors ${
        sortKey === k ? 'text-primary' : 'text-tertiary hover:text-secondary'
      }`}
    >
      {label}
      {sortKey === k && <ArrowUpDown className="w-2.5 h-2.5" strokeWidth={2} />}
    </button>
  )

  return (
    <Panel padding="none">
      <div className="px-4 py-3 border-b border-default flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-primary">Per-Asset Breakdown</span>
          <span className="text-2xs text-tertiary font-mono">{data.length} assets</span>
        </div>
        <button
          onClick={onExport}
          className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-tertiary hover:text-secondary hover:bg-surface transition-colors"
        >
          <Download className="w-3 h-3" strokeWidth={1.5} /> Export
        </button>
      </div>

      {/* Sort bar */}
      <div className="flex items-center gap-4 px-4 py-1.5 border-b border-default/50 bg-surface/30">
        <span className="text-[10px] font-medium uppercase tracking-wider text-tertiary">Asset</span>
        <SortButton k="pnl" label="P&L" />
        <SortButton k="n_trades" label="Trades" />
        <SortButton k="win_rate" label="Win %" />
        <SortButton k="avg_r" label="Avg R" />
      </div>

      {/* Rows */}
      <div className="divide-y divide-default/30">
        {sorted.map(row => (
          <div key={row.asset} className="flex items-center gap-4 px-4 py-2 hover:bg-surface/40 transition-colors">
            <span className="text-xs font-mono font-semibold text-primary w-12 shrink-0">{row.asset}</span>
            <div className="flex-1 flex items-center gap-2">
              <div className="flex-1 h-2 rounded-full bg-surface overflow-hidden">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${Math.abs(row.pnl) / maxPnL * 100}%`,
                    backgroundColor: getPnLColor(row.pnl),
                    marginLeft: row.pnl >= 0 ? 'auto' : '0',
                  }}
                />
              </div>
              <span className={`text-xs font-mono tabular-nums font-medium w-20 text-right ${row.pnl >= 0 ? 'text-signal-long' : 'text-signal-short'}`}>
                {formatPnl(row.pnl)}
              </span>
            </div>
            <span className="text-xs font-mono tabular-nums text-secondary w-10 text-right">{row.n_trades}</span>
            <span className={`text-xs font-mono tabular-nums w-14 text-right ${row.win_rate >= 0.5 ? 'text-signal-long' : 'text-signal-short'}`}>
              {formatPct(row.win_rate)}
            </span>
            <span className={`text-xs font-mono tabular-nums font-medium w-12 text-right ${row.avg_r >= 0 ? 'text-signal-long' : 'text-signal-short'}`}>
              {row.avg_r.toFixed(1)}
            </span>
          </div>
        ))}
      </div>
    </Panel>
  )
}

function TradeList({ trades, onInspect }: { trades: TradeAttributionRecord[]; onInspect: (t: TradeAttributionRecord) => void }) {
  const [search, setSearch] = useState('')
  const [assetFilter, setAssetFilter] = useState<string>('all')
  const [sideFilter, setSideFilter] = useState<'all' | 'buy' | 'sell'>('all')

  const assets = useMemo(() => [...new Set(trades.map(t => t.asset))].sort(), [trades])

  const filtered = useMemo(() => {
    return trades.filter(t => {
      if (assetFilter !== 'all' && t.asset !== assetFilter) return false
      if (sideFilter !== 'all' && t.side.toLowerCase() !== sideFilter) return false
      if (search) {
        const q = search.toLowerCase()
        return (
          t.asset.toLowerCase().includes(q) ||
          t.trade_id.toLowerCase().includes(q) ||
          (t.exit_exit_reason || '').toLowerCase().includes(q)
        )
      }
      return true
    })
  }, [trades, assetFilter, sideFilter, search])

  const maxDisplay = 100
  const display = filtered.length > maxDisplay ? filtered.slice(0, maxDisplay) : filtered

  return (
    <Panel padding="none">
      <div className="px-4 py-3 border-b border-default">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-primary">Trade List</span>
            <span className="text-2xs text-tertiary font-mono">{trades.length} total</span>
            {filtered.length < trades.length && (
              <span className="text-2xs text-tertiary font-mono">· {filtered.length} filtered</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 flex-1 px-2 py-1 rounded-md bg-surface border border-default">
            <Search className="w-3 h-3 text-tertiary shrink-0" strokeWidth={1.5} />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search trades…"
              className="flex-1 bg-transparent text-xs text-primary placeholder:text-muted outline-none"
            />
            {search && (
              <button onClick={() => setSearch('')} className="text-tertiary hover:text-secondary text-[10px] px-1">✕</button>
            )}
          </div>
          <select
            value={assetFilter}
            onChange={e => setAssetFilter(e.target.value)}
            className="text-[10px] bg-surface border border-default rounded px-2 py-1 text-primary outline-none"
            aria-label="Filter by asset"
          >
            <option value="all">All assets</option>
            {assets.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
          <select
            value={sideFilter}
            onChange={e => setSideFilter(e.target.value as typeof sideFilter)}
            className="text-[10px] bg-surface border border-default rounded px-2 py-1 text-primary outline-none"
            aria-label="Filter by side"
          >
            <option value="all">All sides</option>
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
          </select>
        </div>
      </div>

      <div className="divide-y divide-default/30 max-h-[480px] overflow-y-auto">
        {display.length === 0 ? (
          <div className="py-8 text-center text-xs text-tertiary">No matching trades</div>
        ) : (
          display.map(t => (
            <button
              key={t.trade_id}
              onClick={() => onInspect(t)}
              className="w-full flex items-center gap-3 px-4 py-2 hover:bg-surface/40 transition-colors text-left"
            >
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${t.realized_pnl >= 0 ? 'bg-signal-long' : 'bg-signal-short'}`} />
              <span className="text-xs font-mono font-semibold text-primary w-12 shrink-0">{t.asset}</span>
              <span className={`text-[10px] font-mono font-medium w-10 ${t.side === 'long' ? 'text-signal-long' : 'text-signal-short'}`}>
                {t.side.toUpperCase()}
              </span>
              <span className="text-[10px] text-tertiary font-mono flex-1 truncate">{t.trade_id.slice(0, 12)}</span>
              <span className={`text-xs font-mono tabular-nums font-medium ${t.realized_pnl >= 0 ? 'text-signal-long' : 'text-signal-short'}`}>
                {formatPnl(t.realized_pnl)}
              </span>
              <span className={`text-[10px] font-mono tabular-nums w-10 text-right ${t.exit_realized_r >= 0 ? 'text-signal-long' : 'text-signal-short'}`}>
                {t.exit_realized_r.toFixed(1)}R
              </span>
              <span className="text-[10px] text-tertiary font-mono">{t.exit_exit_reason}</span>
            </button>
          ))
        )}
        {filtered.length > maxDisplay && (
          <div className="py-3 text-center text-[10px] text-tertiary">
            Showing {maxDisplay} of {filtered.length} trades — use filters to narrow results
          </div>
        )}
      </div>
    </Panel>
  )
}

// ── Main Component ─────────────────────────────────────────────────

export default function PnLDrillDown() {
  const [aggregation, setAggregation] = useState<TimeAggregation>('daily')
  const [inspectedTrade, setInspectedTrade] = useState<TradeAttributionRecord | null>(null)
  const { data: attrTrades, isPending: tradesLoading } = useAttributionTrades(500)
  const trades = attrTrades ?? []

  const aggregated = useMemo(() => aggregateTrades(trades, aggregation), [trades, aggregation])

  const totalPnL = aggregated.totalPnL
  const winRate = aggregated.totalTrades > 0
    ? trades.filter(t => t.realized_pnl > 0).length / trades.length
    : 0
  const avgR = aggregated.totalTrades > 0
    ? trades.reduce((a, t) => a + t.exit_realized_r, 0) / trades.length
    : 0
  const profitFactor = aggregated.totalTrades > 0
    ? (() => {
        const gains = trades.filter(t => t.realized_pnl > 0).reduce((a, t) => a + t.realized_pnl, 0)
        const losses = Math.abs(trades.filter(t => t.realized_pnl < 0).reduce((a, t) => a + t.realized_pnl, 0))
        return losses > 0 ? gains / losses : trades.some(t => t.realized_pnl < 0) ? 0 : Infinity
      })()
    : 0

  const handleExport = useCallback(() => {
    const rows = aggregated.byAsset.map(a => ({
      asset: a.asset,
      pnl: a.pnl.toFixed(2),
      n_trades: a.n_trades,
      win_rate: (a.win_rate * 100).toFixed(1) + '%',
      avg_r: a.avg_r.toFixed(2),
    }))
    const csv = [
      'asset,pnl,n_trades,win_rate,avg_r',
      ...rows.map(r => `${r.asset},${r.pnl},${r.n_trades},${r.win_rate},${r.avg_r}`),
    ].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `pnl-breakdown-${Date.now()}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }, [aggregated])

  const closeInspector = useCallback(() => setInspectedTrade(null), [])

  // Memoize KPI card icons to make React.memo on KpiCard effective
  const kpiIcons = useMemo(() => ({
    pnl: totalPnL >= 0 ? <TrendingUp className="w-4 h-4" strokeWidth={1.5} /> : <TrendingDown className="w-4 h-4" strokeWidth={1.5} />,
    winRate: <Target className="w-4 h-4" strokeWidth={1.5} />,
    avgR: <BarChart3 className="w-4 h-4" strokeWidth={1.5} />,
    profitFactor: <DollarSign className="w-4 h-4" strokeWidth={1.5} />,
  }), [totalPnL])

  return (
    <>
      <div className={SECTION_SPACING}>
        {/* KPI Cards Row */}
        <EntranceAnimator variant="fade-up">
          <div className={`grid-cols-2 lg:grid-cols-4 ${GRID_GAP} grid`}>
            <KpiCard
              label="Total P&L"
              value={formatPnl(totalPnL)}
              color={getPnLColor(totalPnL)}
              icon={kpiIcons.pnl}
              sub={`${aggregated.totalTrades} trades`}
            />
            <KpiCard
              label="Win Rate"
              value={formatPct(winRate)}
              color={winRate >= 0.5 ? 'var(--color-signal-long)' : 'var(--color-signal-short)'}
              icon={kpiIcons.winRate}
            />
            <KpiCard
              label="Avg R"
              value={avgR.toFixed(2)}
              color={avgR >= 0 ? 'var(--color-signal-long)' : 'var(--color-signal-short)'}
              icon={kpiIcons.avgR}
            />
            <KpiCard
              label="Profit Factor"
              value={profitFactor === Infinity ? '∞' : profitFactor.toFixed(2)}
              color={profitFactor >= 1.5 ? 'var(--color-signal-long)' : profitFactor >= 1 ? 'var(--color-signal-warn)' : 'var(--color-signal-short)'}
              icon={kpiIcons.profitFactor}
            />
          </div>
        </EntranceAnimator>

        {/* Time Aggregation Selector */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            {(['daily', 'weekly', 'monthly'] as const).map(a => (
              <button
                key={a}
                onClick={() => setAggregation(a)}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                  aggregation === a
                    ? 'bg-panel text-primary border border-default shadow-sm'
                    : 'text-tertiary hover:text-secondary border border-transparent'
                }`}
              >
                {a.charAt(0).toUpperCase() + a.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* Cumulative P&L Time-Series Chart */}
        {aggregated.timeSeries.length > 0 && (
          <EntranceAnimator variant="fade-up">
            <Panel padding="md">
              <SectionHeader
                title="P&L Over Time"
                subtitle={`${aggregated.timeSeries.length} periods · ${aggregation}`}
                accent="emerald"
                meta={
                  <span className={`text-xs font-mono tabular-nums font-bold ${totalPnL >= 0 ? 'text-signal-long' : 'text-signal-short'}`}>
                    {formatPnl(totalPnL)}
                  </span>
                }
              />
              <div className="h-48 mt-2">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={aggregated.timeSeries} margin={chartMargin}>
                    <ChartGradientDefs />
                    <CartesianGrid {...cartesianGridProps} />
                    <XAxis
                      dataKey="period"
                      tick={axisTick}
                      interval="preserveStartEnd"
                      axisLine={{ stroke: 'var(--color-border)' }}
                      tickLine={false}
                    />
                    <YAxis
                      tick={axisTick}
                      axisLine={false}
                      tickLine={false}
                      width={60}
                      tickFormatter={v => v >= 0 ? `$${v.toFixed(0)}` : `-$${Math.abs(v).toFixed(0)}`}
                    />
                    <Tooltip
                      contentStyle={tooltipStyle}
                      labelStyle={tooltipLabelStyle}
                      formatter={(value: number) => [`$${value.toFixed(2)}`, 'PnL']}
                      cursor={chartCursor}
                    />
                    <ReferenceLine y={0} stroke="var(--color-border-strong)" strokeWidth={0.5} />
                    <Area
                      type="monotone"
                      dataKey="cumulative"
                      stroke={totalPnL >= 0 ? 'var(--color-signal-long)' : 'var(--color-signal-short)'}
                      fill={getGradientFill()}
                      fillOpacity={1}
                      strokeWidth={2}
                      dot={false}
                      isAnimationActive={false}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              {/* Screen reader accessible data table for cumulative P&L chart */}
              <ChartDataTable
                title="Cumulative P&L by period"
                columns={[
                  { key: 'period', label: 'Period' },
                  { key: 'pnl', label: 'Period P&L', format: v => `$${Number(v).toFixed(2)}` },
                  { key: 'cumulative', label: 'Cumulative P&L', format: v => `$${Number(v).toFixed(2)}` },
                  { key: 'n_trades', label: 'Trades', format: v => String(v) },
                ]}
                data={aggregated.timeSeries as unknown as Record<string, unknown>[]}
                caption={`Cumulative P&L chart data for ${aggregation} aggregation — ${aggregated.timeSeries.length} periods`}
              />
            </Panel>
          </EntranceAnimator>
        )}

        {/* Per-Period Bar Chart */}
        {aggregated.timeSeries.length > 0 && (
          <EntranceAnimator variant="fade-up">
            <Panel padding="md">
              <SectionHeader
                title={`Period P&L — ${aggregation}`}
                accent="emerald"
              />
              <div className="h-40 mt-2">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={aggregated.timeSeries} margin={chartMargin}>
                    <CartesianGrid {...cartesianGridProps} />
                    <XAxis dataKey="period" tick={axisTick} interval="preserveStartEnd" axisLine={{ stroke: 'var(--color-border)' }} tickLine={false} />
                    <YAxis tick={axisTick} axisLine={false} tickLine={false} width={50} tickFormatter={v => `$${v.toFixed(0)}`} />
                    <Tooltip contentStyle={tooltipStyle} formatter={(value: number) => [`$${value.toFixed(2)}`, 'PnL']} cursor={chartCursor} />
                    <ReferenceLine y={0} stroke="var(--color-border-strong)" strokeWidth={0.5} />
                    <Bar dataKey="pnl" radius={[2, 2, 0, 0]}>
                      {aggregated.timeSeries.map((entry, i) => (
                        <Cell key={i} fill={entry.pnl >= 0 ? 'var(--color-signal-long)' : 'var(--color-signal-short)'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              {/* Screen reader accessible data table for per-period bar chart */}
              <ChartDataTable
                title="Period P&L breakdown"
                columns={[
                  { key: 'period', label: 'Period' },
                  { key: 'pnl', label: 'P&L', format: v => `$${Number(v).toFixed(2)}` },
                  { key: 'n_trades', label: 'Trades', format: v => String(v) },
                ]}
                data={aggregated.timeSeries as unknown as Record<string, unknown>[]}
                caption={`Period P&L chart data for ${aggregation} aggregation — ${aggregated.timeSeries.length} periods`}
              />
            </Panel>
          </EntranceAnimator>
        )}

        {/* Per-Asset Breakdown */}
        {aggregated.byAsset.length > 0 && (
          <EntranceAnimator variant="fade-up">
            <AssetPnLTable data={aggregated.byAsset} onExport={handleExport} />
          </EntranceAnimator>
        )}

        {/* Trade List — progressive disclosure via ExpandableSection */}
        {trades.length > 0 && (
          <EntranceAnimator variant="fade-up">
            <ExpandableSection
              title="Trade List"
              defaultOpen={false}
              badge={`${trades.length} trades`}
            >
              <TradeList trades={trades} onInspect={setInspectedTrade} />
            </ExpandableSection>
          </EntranceAnimator>
        )}

        {trades.length === 0 && !tradesLoading && (
          <div className="py-12 text-center">
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-surface border border-default mb-3">
              <BarChart3 className="w-6 h-6 text-tertiary" strokeWidth={1.5} />
            </div>
            <p className="text-sm text-tertiary">No closed trades yet</p>
            <p className="text-xs text-muted mt-1">P&L analysis will appear once trades are settled</p>
          </div>
        )}
      </div>

      {/* Trade Inspector Modal */}
      {inspectedTrade && (
        <TradeInspectorModal
          asset={inspectedTrade.asset}
          entryDate={inspectedTrade.entry_date}
          exitDate={inspectedTrade.exit_date}
          onClose={closeInspector}
        />
      )}
    </>
  )
}
