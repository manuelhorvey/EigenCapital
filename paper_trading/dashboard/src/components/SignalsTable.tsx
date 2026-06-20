import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { usePortfolioState } from '../hooks/usePortfolioState'
import { confidenceToPercent, formatAssetPrice } from '../utils/format'
import DataTable, { type ColumnDef } from './ui/DataTable'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import EmptyState from './ui/EmptyState'
import { TableSkeleton } from './ui/Skeleton'
import Badge, { signalToBadge } from './ui/Badge'

function confClass(conf: number): string {
  if (conf >= 60) return 'text-gov-green'
  if (conf >= 45) return 'text-gov-yellow'
  return 'text-gov-red'
}

function ddClass(dd: number): string {
  if (dd > -3) return 'text-gov-green'
  if (dd > -5) return 'text-gov-yellow'
  return 'text-gov-red'
}

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
}

export default function SignalsTable() {
  const [search, setSearch] = useState('')
  const { data, isPending } = usePortfolioState()

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
        return {
          name,
          signal: sig?.signal ?? 'FLAT',
          confidence: confidenceToPercent(sig?.confidence),
          price: sig?.close_price ?? m?.current_price ?? 0,
          alloc,
          ret: m?.mtm_return ?? 0,
          dd: m?.drawdown ?? 0,
          sellOnly: asset.sell_only ?? false,
          tripwireActive: asset.tripwire_active ?? false,
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
          {r.sellOnly && (
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
      minWidth: '80px',
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
          <span className={`font-mono tabular-nums text-[10px] ${confClass(r.confidence)}`}>
            {r.confidence.toFixed(0)}
          </span>
        </div>
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
      key: 'alloc',
      label: 'Alloc',
      align: 'right',
      sortable: true,
      sortKey: r => r.alloc,
      render: r => <span className="font-mono text-tertiary tabular-nums">{(r.alloc * 100).toFixed(0)}%</span>,
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
      render: r => <span className={`font-mono tabular-nums ${ddClass(r.dd)}`}>{r.dd.toFixed(2)}</span>,
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
                className="input-terminal w-28 sm:w-32 pl-7 focus:border-strong focus:shadow-[0_0_0_1px_rgba(20,184,166,0.2)]"
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
        />
      )}
    </Panel>
  )
}
