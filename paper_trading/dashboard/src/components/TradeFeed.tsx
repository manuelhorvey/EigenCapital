import { memo, useState, useMemo, useCallback } from 'react'
import { useTrades } from '../hooks/useTrades'
import { formatAssetPrice, formatHeldDuration, safeToFixed } from '../utils/format'
import DataTable, { type ColumnDef } from './ui/DataTable'
import TablePagination from './ui/TablePagination'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import EmptyState from './ui/EmptyState'
import { TableSkeleton } from './ui/Skeleton'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import Badge, { reasonToBadge, signalToBadge } from './ui/Badge'
import type { TradeEntry } from '../hooks/useTrades'
import TradeInspectorModal from './trades/TradeInspectorModal'

const PAGE_SIZE = 10

function reasonLabel(reason?: string): string {
  const r = reason?.toLowerCase() ?? ''
  if (r === 'tp' || r === 'tp_hit') return 'TP'
  if (r === 'sl' || r === 'sl_hit' || r === 'stop_loss') return 'SL'
  if (r === 'signal_flip' || r === 'flip') return 'FLIP'
  return reason ?? '—'
}

function TradeFeed() {
  const [page, setPage] = useState(0)
  const [selectedTrade, setSelectedTrade] = useState<TradeEntry | null>(null)
  const handleRowClick = useCallback((trade: TradeEntry) => setSelectedTrade(trade), [])
  const offset = page * PAGE_SIZE
  const { data: trades, isPending } = useTrades(PAGE_SIZE + 1, offset)
  const { data: engineStatus } = useSystemSnapshot(systemSelectors.engineStatus)
  const rows = useMemo(() => (trades ?? []).slice(0, PAGE_SIZE), [trades])
  const hasMore = (trades?.length ?? 0) > PAGE_SIZE

  const columns: ColumnDef<TradeEntry>[] = useMemo(() => [
    {
      key: 'exit_date',
      label: 'Date',
      sortable: true,
      minWidth: '90px',
      render: t => <span className="font-mono text-tertiary tabular-nums">{t.exit_date?.split(' ')[0] ?? '—'}</span>,
    },
    {
      key: 'asset',
      label: 'Asset',
      sortable: true,
      minWidth: '80px',
      render: t => <span className="font-medium text-primary font-mono">{t.asset ?? '—'}</span>,
    },
    {
      key: 'side',
      label: 'Side',
      sortable: true,
      minWidth: '80px',
      render: t => {
        const { variant, icon } = signalToBadge(t.side ?? '')
        return <Badge variant={variant} icon={icon}>{t.side ?? '—'}</Badge>
      },
    },
    {
      key: 'entry',
      label: 'Entry',
      align: 'right',
      sortable: true,
      sortKey: t => t.entry ?? 0,
      render: t => <span className="font-mono text-secondary tabular-nums">${formatAssetPrice(t.entry)}</span>,
    },
    {
      key: 'exit',
      label: 'Exit',
      align: 'right',
      sortable: true,
      sortKey: t => t.exit ?? 0,
      render: t => <span className="font-mono text-secondary tabular-nums">${formatAssetPrice(t.exit)}</span>,
    },
    {
      key: 'return',
      label: 'Return',
      align: 'right',
      sortable: true,
      sortKey: t => (t.return ?? 0) * 100,
      render: t => {
        const ret = (t.return ?? 0) * 100
        return (
          <span className={`font-mono tabular-nums font-semibold ${ret >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
            {ret >= 0 ? '+' : ''}{safeToFixed(ret, 2)}%
          </span>
        )
      },
    },
    {
      key: 'bars',
      label: 'Held',
      align: 'right',
      sortable: true,
      sortKey: t => t.bars ?? 0,
      render: t => (
        <span
          className={`font-mono tabular-nums text-tertiary${t.bars != null && t.bars < 0 ? ' text-gov-red' : ''}`}
          title={t.bars != null && t.bars < 0 ? 'Stale data — trade timestamp predates engine start' : undefined}
        >
          {formatHeldDuration(t.bars)}
        </span>
      ),
    },
    {
      key: 'reason',
      label: 'Reason',
      align: 'right',
      render: t => (
        <Badge variant={reasonToBadge(t.reason)}>{reasonLabel(t.reason)}</Badge>
      ),
    },
  ], [])

  if (isPending) return <TableSkeleton rows={4} />

  const engineStart = engineStatus?.start_time

  if (rows.length === 0) {
    return (
      <Panel padding="md">
        <SectionHeader title="Recent Trades" accent="emerald" />
        <EmptyState
          message={engineStart ? `No trades recorded yet — engine started ${engineStart.split('T')[0]}` : 'No trades closed yet'}
          compact
        />
      </Panel>
    )
  }

  return (
    <Panel className="overflow-hidden">
      <SectionHeader
        title="Recent Trades"
        accent="emerald"
        meta={
          <TablePagination
            page={page}
            hasMore={hasMore}
            totalItems={(trades?.length ?? 0) + offset}
            onPrev={() => setPage(p => Math.max(0, p - 1))}
            onNext={() => setPage(p => p + 1)}
          />
        }
      />
      <DataTable
        columns={columns}
        data={rows}
        keyExtractor={t => `${t.asset}_${t.exit_date}_${t.entry_date}_${t.entry}_${t.exit}`}
        compact
        sortable
        defaultSortKey="exit_date"
        defaultSortDir="desc"
        storageKey="trades"
        onRowClick={handleRowClick}
      />
      {selectedTrade && (
        <TradeInspectorModal
          asset={selectedTrade.asset}
          entryDate={selectedTrade.entry_date}
          exitDate={selectedTrade.exit_date}
          onClose={() => setSelectedTrade(null)}
        />
      )}
    </Panel>
  )
}

export default memo(TradeFeed)
