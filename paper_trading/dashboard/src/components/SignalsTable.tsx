import { memo, useMemo, useState } from 'react'
import { Search, ExternalLink } from 'lucide-react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { useSelectedAsset } from '../hooks/useSelectedAsset'
import { systemSelectors } from '../selectors/system'
import { confidenceToPercent, formatAssetPrice } from '../utils/format'
import DataTable, { type ColumnDef } from './ui/DataTable'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import EmptyState from './ui/EmptyState'
import { TableSkeleton } from './ui/Skeleton'
import Badge, { signalToBadge } from './ui/Badge'
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
  gatesPassed: string | null
  finalSize: string | null
  unrealizedPnl: number | null
  tradeDuration: string | null
  tpPct: number | null
  slPct: number | null
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
        const openPos = data?.open_positions?.[name]
        let tpPct: number | null = null
        let slPct: number | null = null
        if (pos?.entry && pos?.tp && pos?.sl) {
          if (pos.side === 'long') {
            tpPct = ((pos.tp - pos.entry) / pos.entry) * 100
            slPct = ((pos.entry - pos.sl) / pos.entry) * 100
          } else {
            tpPct = ((pos.entry - pos.tp) / pos.entry) * 100
            slPct = ((pos.sl - pos.entry) / pos.entry) * 100
          }
        }

        // Determine gates trace summary
        const gt = asset.gates_trace
        const gatesAborted = gt ? Object.entries(gt).filter(([, v]) => !v).map(([k]) => k) : []
        const gatesPassed = gatesAborted.length === 0 ? 'PASS' : `BLOCKED:${gatesAborted.join(',')}`

        // Determine sizing result
        const sc = asset.sizing_chain
        const finalSize = sc?.final_pct != null ? `${(Number(sc.final_pct) * 100).toFixed(1)}%` : null

        // Determine trade duration
        const probHist = openPos?.prob_history
        let tradeDuration: string | null = null
        if (probHist && probHist.length > 0 && pos) {
          const entryDate = probHist[0]?.date
          if (entryDate) {
            const elapsed = Date.now() - new Date(entryDate).getTime()
            const hours = Math.floor(elapsed / 3600000)
            tradeDuration = hours < 24 ? `${hours}h` : `${Math.floor(hours / 24)}d`
          }
        }

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
          gatesPassed,
          finalSize,
          unrealizedPnl: pos?.unrealized_pnl != null ? pos.unrealized_pnl : null,
          tradeDuration,
          tpPct,
          slPct,
        }
      })
  }, [data, search])

  const columns: ColumnDef<SignalRow>[] = useMemo(() => [
    {
      key: 'name',
      label: 'Asset',
      sortable: true,
      minWidth: '80px',
      render: r => (
        <span className="flex items-center gap-1.5">
          <span className="font-semibold text-primary text-xs font-mono">{r.name}</span>
          {r.halted && (
            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full leading-none bg-gov-red-muted text-gov-red border border-gov-red/20">
              HALT
            </span>
          )}
          {!r.halted && r.sellOnly && (
            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full leading-none ${
              r.tripwireActive
                ? 'bg-gov-red-muted text-gov-red border border-gov-red/20 animate-pulse'
                : 'bg-gov-yellow-muted text-gov-yellow border border-gov-yellow/20'
            }`}>
              {r.tripwireActive ? 'TRIPWIRE' : 'S-O'}
            </span>
          )}
        </span>
      ),
    },
    {
      key: 'signal',
      label: 'Signal',
      sortable: true,
      minWidth: '70px',
      render: r => {
        const { variant, icon } = signalToBadge(r.signal)
        return <Badge variant={variant} icon={icon}>{r.signal === 'BUY' ? 'LONG' : r.signal === 'SELL' ? 'SHORT' : 'FLAT'}</Badge>
      },
    },
    {
      key: 'confidence',
      label: 'Conf',
      align: 'right',
      sortable: true,
      sortKey: r => r.confidence,
      render: r => (
        <div className="flex items-center gap-1.5 justify-end">
          <div className="w-12 h-1 bg-panel rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-300 ${
                r.confidence >= 60 ? 'bg-gov-green' : r.confidence >= 45 ? 'bg-gov-yellow' : 'bg-gov-red'
              }`}
              style={{ width: `${r.confidence}%` }}
            />
          </div>
          <span className={`font-mono tabular-nums text-[10px] ${governanceText[confToState(r.confidence)]}`}>
            {r.confidence.toFixed(0)}
          </span>
        </div>
      ),
    },
    {
      key: 'gatesPassed',
      label: 'Gates',
      sortable: true,
      minWidth: '80px',
      sortKey: r => r.gatesPassed === 'PASS' ? 1 : 0,
      render: r => (
        <span className={`text-[10px] font-mono font-semibold ${r.gatesPassed === 'PASS' ? 'text-gov-green' : 'text-gov-red'}`}>
          {r.gatesPassed === 'PASS' ? '✓ PASS' : r.gatesPassed ?? '—'}
        </span>
      ),
    },
    {
      key: 'finalSize',
      label: 'Size',
      align: 'right',
      sortable: true,
      sortKey: r => r.finalSize ? parseFloat(r.finalSize) : -1,
      render: r => (
        <span className={`font-mono tabular-nums text-[10px] ${r.finalSize ? 'text-primary' : 'text-tertiary'}`}>
          {r.finalSize ?? '—'}
        </span>
      ),
    },
    {
      key: 'unrealizedPnl',
      label: 'uPnL',
      align: 'right',
      sortable: true,
      sortKey: r => r.unrealizedPnl ?? 0,
      render: r => (
        <span className={`font-mono tabular-nums ${r.unrealizedPnl != null ? (r.unrealizedPnl >= 0 ? 'text-gov-green' : 'text-gov-red') : 'text-tertiary'}`}>
          {r.unrealizedPnl != null ? `${r.unrealizedPnl >= 0 ? '+' : ''}${r.unrealizedPnl.toFixed(2)}%` : '—'}
        </span>
      ),
    },
    {
      key: 'tradeDuration',
      label: 'Age',
      align: 'right',
      sortable: true,
      sortKey: r => r.tradeDuration ? (r.tradeDuration.endsWith('d') ? parseInt(r.tradeDuration) * 24 : parseInt(r.tradeDuration)) : -1,
      render: r => (
        <span className="font-mono tabular-nums text-tertiary text-[10px]">
          {r.tradeDuration ?? '—'}
        </span>
      ),
    },
    {
      key: 'price',
      label: 'Price',
      align: 'right',
      sortable: true,
      sortKey: r => r.price,
      render: r => <span className="font-mono text-secondary tabular-nums">{formatAssetPrice(r.price)}</span>,
    },
    {
      key: 'ret',
      label: 'Ret',
      align: 'right',
      sortable: true,
      sortKey: r => r.ret,
      render: r => (
        <span className={`font-mono tabular-nums ${r.ret >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
          {r.ret.toFixed(2)}
        </span>
      ),
    },
    {
      key: 'dd',
      label: 'DD',
      align: 'right',
      sortable: true,
      sortKey: r => r.dd,
      render: r => <span className={`font-mono tabular-nums ${governanceText[ddToState(r.dd)]}`}>{r.dd.toFixed(2)}</span>,
    },
    {
      key: 'actions',
      label: '',
      align: 'center',
      width: '32px',
      render: r => (
        <button
          type="button"
          onClick={(e: React.MouseEvent) => { e.stopPropagation(); setDeepDiveAsset(r.name) }}
          className="p-1 rounded hover:bg-panel transition-colors text-tertiary hover:text-primary"
          title={`Deep dive: ${r.name}`}
        >
          <ExternalLink className="w-3 h-3" strokeWidth={1.5} />
        </button>
      ),
    },
  ], [])

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
                className="input-terminal w-28 sm:w-32 pl-7 focus:border-strong focus:shadow-[0_0_0_1px_rgba(20,184,166,0.2)] min-h-[36px] sm:min-h-0"
              />
            </div>
            <span className="text-[10px] text-tertiary font-mono tabular-nums bg-surface/50 px-1.5 py-0.5 rounded">{rows.length}</span>
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
          defaultSortKey="confidence"
          defaultSortDir="desc"
          storageKey="signals"
          onRowClick={r => setSelectedAsset(r.name)}
        />
      )}
    </Panel>
  )
}

export default memo(SignalsTable)
