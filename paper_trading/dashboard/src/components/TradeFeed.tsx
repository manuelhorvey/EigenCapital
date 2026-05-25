import { useState, useMemo } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useTrades } from '../hooks/useTrades'
import { formatAssetPrice, formatHeldDuration, safeToFixed } from '../utils/format'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import EmptyState from './ui/EmptyState'
import { TableSkeleton } from './ui/Skeleton'
import { usePortfolioState } from '../hooks/usePortfolioState'

const PAGE_SIZE = 10

function reasonPill(reason?: string) {
  const r = reason?.toLowerCase() ?? ''
  if (r === 'tp' || r === 'tp_hit') return 'signal-pill-buy'
  if (r === 'sl' || r === 'sl_hit' || r === 'stop_loss') return 'signal-pill-sell'
  if (r === 'signal_flip' || r === 'flip') return 'signal-pill-flat'
  return 'signal-pill-flat'
}

export default function TradeFeed() {
  const [page, setPage] = useState(0)
  const offset = page * PAGE_SIZE
  const { data: trades, isPending } = useTrades(PAGE_SIZE + 1, offset)
  const { data: portfolio } = usePortfolioState()
  const rows = useMemo(() => (trades ?? []).slice(0, PAGE_SIZE), [trades])
  const hasMore = (trades?.length ?? 0) > PAGE_SIZE

  if (isPending) return <TableSkeleton rows={4} />

  const engineStart = portfolio?.engine_status?.start_time

  if (rows.length === 0) {
    return (
      <Panel padding="md">
        <SectionHeader title="Recent Trades" accent="blue" />
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
        accent="blue"
        meta={
          <div className="flex items-center gap-2">
            <span className="text-2xs text-tertiary font-mono tabular-nums">
              Page {page + 1} of {hasMore ? `${page + 2}+` : page + 1} · {(trades?.length ?? 0) + offset} total
            </span>
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
                  key={`${t.asset}_${t.exit_date}_${t.entry_date}_${t.entry}_${t.exit}`}
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
                    {safeToFixed(ret, 2)}%
                  </td>
                  <td
                    className="py-2 pr-4 text-right font-mono tabular-nums text-tertiary"
                    title={t.bars != null && t.bars < 0 ? 'Stale data — trade timestamp predates engine start' : undefined}
                  >
                    <span className={t.bars != null && t.bars < 0 ? 'text-gov-red' : ''}>
                      {formatHeldDuration(t.bars)}
                    </span>
                  </td>
                  <td className="py-2 text-right">
                    <span className={`signal-pill ${reasonPill(t.reason)}`}>
                      {t.reason === 'tp' || t.reason === 'TP' ? 'TP' :
                       t.reason === 'sl' || t.reason === 'SL' || t.reason === 'stop_loss' ? 'SL' :
                       t.reason === 'signal_flip' ? 'FLIP' :
                       t.reason ?? '—'}
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
