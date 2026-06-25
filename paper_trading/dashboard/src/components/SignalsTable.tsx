import { memo, useMemo, useState } from 'react'
import { Search, TrendingUp, TrendingDown, Minus, Activity } from 'lucide-react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { useSelectedAsset } from '../hooks/useSelectedAsset'
import { systemSelectors } from '../selectors/system'
import { confidenceToPercent, formatAssetPrice } from '../utils/format'
import DataTable, { type ColumnDef } from './ui/DataTable'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import EmptyState from './ui/EmptyState'
import { TableSkeleton } from './ui/Skeleton'
import { confToState, ddToState, governanceText } from './ui/governance'

interface SignalRow {
  name: string
  signal: string
  confidence: number
  price: number
  alloc: number
  ret: number
  dd: number
  sellOnly: boolean
  tripwireActive: boolean
  halted: boolean
  haltReasons: string[]
  unrealizedPnl: number | null
  nTrades: number
  winRate: number | null
  sharpe: number | null
  exitTpRate: number | null
  exitSlRate: number | null
}

// One word per state, used for the left accent + the inline label. No icon soup.
function rowState(r: SignalRow): 'halted' | 'tripwire' | 'sellOnly' | 'normal' {
  if (r.halted) return 'halted'
  if (r.sellOnly && r.tripwireActive) return 'tripwire'
  if (r.sellOnly) return 'sellOnly'
  return 'normal'
}

const stateAccent: Record<ReturnType<typeof rowState>, string> = {
  halted: 'border-l-gov-red',
  tripwire: 'border-l-gov-red',
  sellOnly: 'border-l-gov-yellow',
  normal: 'border-l-transparent',
}

const stateLabel: Record<ReturnType<typeof rowState>, string | null> = {
  halted: 'Halted',
  tripwire: 'Tripwire',
  sellOnly: 'Sell only',
  normal: null,
}

const stateLabelClass: Record<ReturnType<typeof rowState>, string> = {
  halted: 'text-gov-red',
  tripwire: 'text-gov-red',
  sellOnly: 'text-gov-yellow',
  normal: '',
}

function DirectionGlyph({ signal }: { signal: string }) {
  if (signal === 'BUY') return <TrendingUp className="w-3.5 h-3.5 text-gov-green" strokeWidth={2.5} />
  if (signal === 'SELL') return <TrendingDown className="w-3.5 h-3.5 text-gov-red" strokeWidth={2.5} />
  return <Minus className="w-3.5 h-3.5 text-tertiary" strokeWidth={2} />
}

// Single horizontal bar, used for confidence and exit mix alike so the table
// has one visual language for "a quantity out of 100" instead of three.
function Bar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="w-12 h-1 bg-surface rounded-full overflow-hidden">
      <div
        className="h-full rounded-full transition-all duration-300"
        style={{ width: `${Math.max(0, Math.min(pct, 100))}%`, backgroundColor: color }}
      />
    </div>
  )
}

function SignalsTable() {
  const [search, setSearch] = useState('')
  const { data, isPending } = useSystemSnapshot(systemSelectors.snapshot)
  const { setSelectedAsset, setDeepDiveAsset } = useSelectedAsset()

  const rows = useMemo(() => {
    if (!data?.assets) return []
    return Object.entries(data.assets)
      .filter(([name]) => name in (data.portfolio?.allocations ?? {}))
      .filter(([name]) => name.toLowerCase().includes(search.toLowerCase()))
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, asset]) => {
        const sig = asset.last_signal
        const m = asset.metrics
        const alloc = data.portfolio?.allocations?.[name] ?? 0
        const pos = m?.position
        const exitReasons = m?.exit_reasons
        return {
          name,
          signal: asset.final_signal ?? sig?.signal ?? 'FLAT',
          confidence: confidenceToPercent(sig?.confidence),
          price: sig?.close_price ?? m?.current_price ?? 0,
          alloc,
          ret: m?.mtm_return ?? 0,
          dd: m?.drawdown ?? 0,
          sellOnly: asset.sell_only ?? false,
          tripwireActive: asset.tripwire_active ?? false,
          halted: asset.halt?.halted ?? false,
          haltReasons: asset.halt?.reasons ?? [],
          unrealizedPnl: pos?.unrealized_pnl ?? null,
          nTrades: m?.n_trades ?? 0,
          winRate: m?.win_rate ?? null,
          sharpe: m?.sharpe_ratio ?? null,
          exitTpRate: exitReasons?.tp_rate ?? null,
          exitSlRate: exitReasons?.sl_rate ?? null,
        }
      })
  }, [data, search])

  const columns: ColumnDef<SignalRow>[] = useMemo(() => [
    // Asset — name plus a one-word state label when it isn't trading normally.
    // The row's left border (applied by rowClassName below) already carries
    // the halted/tripwire/sell-only color, so this cell just needs the word.
    {
      key: 'name',
      label: 'Asset',
      sortable: true,
      minWidth: '90px',
      render: r => {
        const state = rowState(r)
        const label = stateLabel[state]
        return (
          <div className="min-w-0">
            <span className="font-semibold text-primary text-xs font-mono">{r.name}</span>
            {label && (
              <div className={`text-[10px] leading-tight ${stateLabelClass[state]}`}>{label}</div>
            )}
          </div>
        )
      },
    },

    // Signal — direction and confidence belong together: a confidence number
    // means nothing without knowing which way it's pointing.
    {
      key: 'signal',
      label: 'Signal',
      minWidth: '90px',
      sortable: true,
      sortKey: r => r.confidence,
      render: r => (
        <div className="flex items-center gap-2">
          <DirectionGlyph signal={r.signal} />
          <Bar
            pct={r.confidence}
            color={
              r.confidence >= 60
                ? 'var(--color-gov-green)'
                : r.confidence >= 45
                  ? 'var(--color-gov-yellow)'
                  : 'var(--color-gov-red)'
            }
          />
          <span className={`font-mono tabular-nums text-[10px] ${governanceText[confToState(r.confidence)]}`}>
            {r.confidence.toFixed(0)}
          </span>
        </div>
      ),
    },

    // Track record — Sharpe is the headline number; trade count and win rate
    // are the context that tells you whether to trust the Sharpe at all.
    // A Sharpe of 2.4 on 3 trades and a Sharpe of 2.4 on 80 trades are
    // different facts, so they're printed together, not three columns apart.
    {
      key: 'trackRecord',
      label: 'Track record',
      align: 'right',
      minWidth: '90px',
      sortable: true,
      sortKey: r => r.sharpe ?? -999,
      render: r => {
        if (r.sharpe == null) return <span className="text-[10px] text-tertiary">—</span>
        const good = r.sharpe >= 0.5
        return (
          <div className="text-right">
            <span className={`font-mono tabular-nums text-xs font-semibold ${good ? 'text-gov-green' : 'text-gov-red'}`}>
              {r.sharpe.toFixed(1)}
            </span>
            <div className="font-mono tabular-nums text-[10px] text-tertiary">
              {r.nTrades} tr{r.winRate != null ? ` · ${(r.winRate * 100).toFixed(0)}%` : ''}
            </div>
          </div>
        )
      },
    },

    // Return / drawdown — the realized risk-reward pair. Return on top,
    // drawdown below it in the governance color scale, same cell because
    // you read these as a ratio, not as two separate facts.
    {
      key: 'returnDd',
      label: 'Ret / DD',
      align: 'right',
      minWidth: '64px',
      sortable: true,
      sortKey: r => r.ret,
      render: r => (
        <div className="text-right">
          <span className={`font-mono tabular-nums text-xs ${r.ret >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
            {r.ret >= 0 ? '+' : ''}{r.ret.toFixed(2)}
          </span>
          <div className={`font-mono tabular-nums text-[10px] ${governanceText[ddToState(r.dd)]}`}>
            {r.dd.toFixed(1)} dd
          </div>
        </div>
      ),
    },

    // Exit mix — replaces the old TP%/SL%/spark trio with one stacked bar.
    // Green segment is take-profit share, red is stop-loss share; the split
    // itself is the information, so it doesn't need two numbers next to it.
    {
      key: 'exitMix',
      label: 'Exit mix',
      align: 'right',
      minWidth: '64px',
      sortable: true,
      sortKey: r => (r.exitTpRate ?? 0) - (r.exitSlRate ?? 0),
      render: r => {
        if (r.exitTpRate == null || r.exitSlRate == null || r.nTrades === 0) {
          return <span className="text-[10px] text-tertiary">—</span>
        }
        const total = r.exitTpRate + r.exitSlRate
        const tpShare = total > 0 ? (r.exitTpRate / total) * 100 : 50
        return (
          <div className="flex justify-end">
            <div className="w-12 h-1.5 rounded-full overflow-hidden flex bg-surface">
              <div className="h-full bg-gov-green" style={{ width: `${tpShare}%` }} />
              <div className="h-full bg-gov-red" style={{ width: `${100 - tpShare}%` }} />
            </div>
          </div>
        )
      },
    },

    // Allocation — current exposure, with unrealized P&L as a colored sign
    // next to the percentage rather than an unlabeled bar with no number on it.
    {
      key: 'alloc',
      label: 'Alloc',
      align: 'right',
      minWidth: '56px',
      sortable: true,
      sortKey: r => r.alloc,
      render: r => (
        <div className="text-right">
          <span className="font-mono tabular-nums text-xs text-secondary">{(r.alloc * 100).toFixed(1)}%</span>
          {r.unrealizedPnl != null && (
            <div className={`font-mono tabular-nums text-[10px] ${r.unrealizedPnl >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
              {r.unrealizedPnl >= 0 ? '+' : ''}{r.unrealizedPnl.toFixed(0)} uPnL
            </div>
          )}
        </div>
      ),
    },

    // Deep dive — hidden until hover so it doesn't sit on the row at 50%
    // opacity competing for attention all the time.
    {
      key: 'actions',
      label: '',
      align: 'center',
      width: '28px',
      render: r => (
        <button
          type="button"
          onClick={(e: React.MouseEvent) => { e.stopPropagation(); setDeepDiveAsset(r.name) }}
          className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-panel transition-opacity text-tertiary hover:text-primary"
          title={`Deep dive: ${r.name}`}
        >
          <Activity className="w-3.5 h-3.5" strokeWidth={1.5} />
        </button>
      ),
    },
  ], [setDeepDiveAsset])

  if (isPending) return <TableSkeleton rows={6} />

  if (rows.length === 0 && !search) {
    return (
      <Panel className="p-4">
        <SectionHeader title="Signals" accent="emerald" />
        <EmptyState message="No assets loaded" compact />
      </Panel>
    )
  }

  return (
    <Panel className="overflow-hidden p-3.5 sm:p-4">
      <SectionHeader
        title="Signals"
        accent="emerald"
        meta={
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-muted pointer-events-none" />
              <input
                type="text"
                placeholder="Filter…"
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="input-terminal w-24 sm:w-32 pl-7 focus:border-strong focus:shadow-[0_0_0_1px_rgba(20,184,166,0.2)] min-h-[36px] sm:min-h-0"
              />
            </div>
            <span className="text-[10px] text-tertiary font-mono tabular-nums bg-surface/50 px-1.5 py-0.5 rounded">
              {rows.length}
            </span>
            <span className="hidden sm:inline-flex text-[10px] text-tertiary font-mono tabular-nums bg-surface/50 px-1.5 py-0.5 rounded">
              {rows.filter(r => r.signal !== 'FLAT').length} active
            </span>
          </div>
        }
      />
      {rows.length === 0 ? (
        <EmptyState message="No assets match filter" compact filtered />
      ) : (
        <DataTable
          columns={columns}
          data={rows}
          keyExtractor={r => r.name}
          sortable
          defaultSortKey="trackRecord"
          defaultSortDir="desc"
          storageKey="signals"
          onRowClick={r => setSelectedAsset(r.name)}
          rowClassName={r => `group border-l-2 ${stateAccent[rowState(r)]}`}
        />
      )}
    </Panel>
  )
}

export default memo(SignalsTable)