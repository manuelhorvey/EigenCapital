import { useState, useMemo } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useTrades } from '../hooks/useTrades'
import { formatAssetPrice } from '../utils/format'
import DataTable, { type ColumnDef } from './ui/DataTable'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import EmptyState from './ui/EmptyState'
import { TableSkeleton } from './ui/Skeleton'

const PAGE_SIZE = 10

interface TradeRow {
  asset: string
  side: string
  entry: number
  exit: number
  exit_date: string
  ret: number
  bars: number | null
  reason: string
}

export default function TradeFeed() {
  const [page, setPage] = useState(0)
  const offset = page * PAGE_SIZE
  const { data: trades, isPending } = useTrades(PAGE_SIZE + 1, offset)
  const rows: TradeRow[] = useMemo(
    () => (trades ?? []).slice(0, PAGE_SIZE).map(t => ({
      asset: t.asset ?? '',
      side: t.side ?? '',
      entry: t.entry ?? 0,
      exit: t.exit ?? 0,
      exit_date: t.exit_date?.split(' ')[0] ?? '',
      ret: (t.return ?? 0) * 100,
      bars: t.bars ?? null,
      reason: t.reason ?? '',
    })),
    [trades],
  )
  const hasMore = (trades?.length ?? 0) > PAGE_SIZE

  const columns: ColumnDef<TradeRow>[] = useMemo(() => [
    {
      key: 'exit_date',
      label: 'Date',
      sortable: true,
      sortKey: r => r.exit_date,
      render: r => <span className="font-mono text-tertiary tabular-nums">{r.exit_date}</span>,
    },
    {
      key: 'asset',
      label: 'Asset',
      sortable: true,
      render: r => <span className="font-medium text-primary font-mono">{r.asset}</span>,
    },
    {
      key: 'side',
      label: 'Side',
      sortable: true,
      render: r => (
        <span className={`signal-pill ${r.side === 'short' || r.side === 'SHORT' ? 'signal-pill-sell' : 'signal-pill-buy'}`}>
          {r.side}
        </span>
      ),
    },
    {
      key: 'entry',
      label: 'Entry',
      align: 'right',
      sortable: true,
      sortKey: r => r.entry,
      render: r => <span className="font-mono text-secondary tabular-nums">${formatAssetPrice(r.entry)}</span>,
    },
    {
      key: 'exit',
      label: 'Exit',
      align: 'right',
      sortable: true,
      sortKey: r => r.exit,
      render: r => <span className="font-mono text-secondary tabular-nums">${formatAssetPrice(r.exit)}</span>,
    },
    {
      key: 'ret',
      label: 'Return',
      align: 'right',
      sortable: true,
      sortKey: r => r.ret,
      render: r => (
        <span className={`font-mono tabular-nums font-semibold ${r.ret >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
          {r.ret >= 0 ? '+' : ''}{r.ret.toFixed(2)}%
        </span>
      ),
    },
    {
      key: 'bars',
      label: 'Held',
      align: 'right',
      sortable: true,
      sortKey: r => r.bars ?? 0,
      render: r => {
        const held = r.bars
        const color = held != null && held > 14 ? 'text-gov-yellow' : held != null && held > 30 ? 'text-gov-red' : 'text-tertiary'
        return <span className={`font-mono tabular-nums ${color}`}>{held != null ? `${held}d` : '—'}</span>
      },
    },
    {
      key: 'reason',
      label: 'Reason',
      align: 'right',
      sortable: true,
      render: r => (
        <span
          className={`signal-pill ${
            r.reason === 'tp' || r.reason === 'TP'
              ? 'signal-pill-buy'
              : r.reason === 'sl' || r.reason === 'SL'
                ? 'signal-pill-sell'
                : 'signal-pill-flat'
          }`}
        >
          {r.reason ?? '—'}
        </span>
      ),
    },
  ], [])

  if (isPending) return <TableSkeleton rows={4} />

  if (rows.length === 0) {
    return (
      <Panel padding="md">
        <SectionHeader title="Recent Trades" accent="blue" />
        <EmptyState message="No trades closed yet" compact />
      </Panel>
    )
  }

  return (
    <Panel className="overflow-hidden p-3.5 sm:p-4">
      <SectionHeader
        title="Recent Trades"
        accent="blue"
        meta={
          <div className="flex items-center gap-2">
            <span className="text-2xs text-tertiary font-mono">p.{page + 1}</span>
            <div className="flex items-center gap-0.5">
              <button
                type="button"
                onClick={() => setPage(p => Math.max(0, p - 1))}
                disabled={page === 0}
                className="p-1 rounded-md border border-default hover:border-strong disabled:opacity-30 transition-colors active:scale-95"
              >
                <ChevronLeft className="w-3 h-3 text-secondary" />
              </button>
              <button
                type="button"
                onClick={() => setPage(p => p + 1)}
                disabled={!hasMore}
                className="p-1 rounded-md border border-default hover:border-strong disabled:opacity-30 transition-colors active:scale-95"
              >
                <ChevronRight className="w-3 h-3 text-secondary" />
              </button>
            </div>
          </div>
        }
      />
      <DataTable
        columns={columns}
        data={rows}
        keyExtractor={r => `${r.asset}_${r.exit_date}_${r.entry}_${r.exit}`}
        sortable
        defaultSortKey="exit_date"
        defaultSortDir="desc"
        storageKey="trades"
        compact
      />
    </Panel>
  )
}
