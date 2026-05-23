import { useState, useMemo } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useTrades } from '../hooks/useTrades'
import { formatAssetPrice } from '../utils/format'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import EmptyState from './ui/EmptyState'
import { TableSkeleton } from './ui/Skeleton'

const PAGE_SIZE = 10

export default function TradeFeed() {
  const [page, setPage] = useState(0)
  const offset = page * PAGE_SIZE
  const { data: trades, isPending } = useTrades(PAGE_SIZE + 1, offset)
  const rows = useMemo(() => (trades ?? []).slice(0, PAGE_SIZE), [trades])
  const hasMore = (trades?.length ?? 0) > PAGE_SIZE

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
    <Panel className="overflow-hidden">
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
      <div className="overflow-x-auto -mx-1">
        <table className="w-full text-xs min-w-[640px]">
          <thead>
            <tr className="border-b border-default">
              <th className="table-header text-left py-2 pr-4">Date</th>
              <th className="table-header text-left py-2 pr-4">Asset</th>
              <th className="table-header text-left py-2 pr-4">Side</th>
              <th className="table-header text-right py-2 pr-4">Entry</th>
              <th className="table-header text-right py-2 pr-4">Exit</th>
              <th className="table-header text-right py-2 pr-4">Return</th>
              <th className="table-header text-right py-2 pr-4">Held</th>
              <th className="table-header text-right py-2">Reason</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t, i) => {
              const ret = (t.return ?? 0) * 100
              return (
                <tr
                  key={`${t.asset}_${t.exit_date}_${t.entry}_${i}`}
                  className={`border-b border-default/40 table-row-hover ${
                    i % 2 === 1 ? 'bg-panel/30' : ''
                  }`}
                >
                  <td className="py-2 pr-4 font-mono text-tertiary tabular-nums">
                    {t.exit_date?.split(' ')[0] ?? '—'}
                  </td>
                  <td className="py-2 pr-4 font-medium text-primary font-mono">{t.asset ?? '—'}</td>
                  <td className="py-2 pr-4">
                    <span
                      className={`signal-pill ${
                        t.side === 'LONG' ? 'signal-pill-buy' : 'signal-pill-sell'
                      }`}
                    >
                      {t.side ?? '—'}
                    </span>
                  </td>
                  <td className="py-2 pr-4 text-right font-mono text-secondary tabular-nums">
                    ${formatAssetPrice(t.entry)}
                  </td>
                  <td className="py-2 pr-4 text-right font-mono text-secondary tabular-nums">
                    ${formatAssetPrice(t.exit)}
                  </td>
                  <td
                    className={`py-2 pr-4 text-right font-mono tabular-nums font-semibold ${
                      ret >= 0 ? 'text-gov-green' : 'text-gov-red'
                    }`}
                  >
                    {ret >= 0 ? '+' : ''}
                    {ret.toFixed(2)}%
                  </td>
                  <td className="py-2 pr-4 text-right font-mono text-tertiary tabular-nums">
                    {t.bars != null ? `${t.bars}d` : '—'}
                  </td>
                  <td className="py-2 text-right">
                    <span
                      className={`signal-pill ${
                        t.reason === 'tp' || t.reason === 'TP'
                          ? 'signal-pill-buy'
                          : t.reason === 'sl' || t.reason === 'SL'
                            ? 'signal-pill-sell'
                            : 'signal-pill-flat'
                      }`}
                    >
                      {t.reason ?? '—'}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
