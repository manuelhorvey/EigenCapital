import { useMemo } from 'react'
import { useTrades } from '../hooks/useTrades'
import { formatAssetPrice } from '../utils/format'

export default function TradeFeed() {
  const { data: trades, isPending } = useTrades()
  const rows = useMemo(() => trades ?? [], [trades])

  if (isPending) {
    return (
      <div className="card-gradient card-border rounded-xl p-4 animate-pulse">
        <div className="h-4 bg-panel rounded w-1/4 mb-4" />
        <div className="space-y-2">
          <div className="h-8 bg-panel rounded" />
          <div className="h-8 bg-panel rounded" />
          <div className="h-8 bg-panel rounded" />
        </div>
      </div>
    )
  }

  if (rows.length === 0) {
    return (
      <div className="card-gradient card-border rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-2 h-2 rounded-full bg-tertiary" />
          <h2 className="text-sm font-semibold text-primary">Recent Trades</h2>
        </div>
        <div className="text-xs text-tertiary text-center py-8">No trades closed yet</div>
      </div>
    )
  }

  return (
    <div className="card-gradient card-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-blue-500/50" />
          <h2 className="text-sm font-semibold text-primary">Recent Trades</h2>
        </div>
        <span className="text-[11px] text-tertiary">{rows.length} trades</span>
      </div>
      <div className="overflow-x-auto -mx-4 px-4">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-default">
              <th className="table-header text-left py-2.5 pr-4">Date</th>
              <th className="table-header text-left py-2.5 pr-4">Asset</th>
              <th className="table-header text-left py-2.5 pr-4">Side</th>
              <th className="table-header text-right py-2.5 pr-4">Entry</th>
              <th className="table-header text-right py-2.5 pr-4">Exit</th>
              <th className="table-header text-right py-2.5 pr-4">Return</th>
              <th className="table-header text-right py-2.5 pr-4">Held</th>
              <th className="table-header text-right py-2.5">Reason</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t, i) => {
              const ret = (t.return ?? 0) * 100
              return (
                <tr
                  key={i}
                  className={`border-b border-default/50 transition-colors hover:bg-panel/50 ${
                    i % 2 === 0 ? '' : 'bg-panel/30'
                  }`}
                >
                  <td className="py-2.5 pr-4 font-mono text-tertiary">{t.exit_date?.split(' ')[0] ?? '—'}</td>
                  <td className="py-2.5 pr-4 font-medium text-primary">{t.asset ?? '—'}</td>
                  <td className="py-2.5 pr-4">
                    <span className={`inline-flex items-center gap-1 font-medium ${
                      t.side === 'LONG' ? 'text-emerald-400' : 'text-red-400'
                    }`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${t.side === 'LONG' ? 'bg-emerald-500' : 'bg-red-500'}`} />
                      {t.side ?? '—'}
                    </span>
                  </td>
                  <td className="py-2.5 pr-4 text-right font-mono text-secondary tabular-nums">
                    ${formatAssetPrice(t.entry)}
                  </td>
                  <td className="py-2.5 pr-4 text-right font-mono text-secondary tabular-nums">
                    ${formatAssetPrice(t.exit)}
                  </td>
                  <td className={`py-2.5 pr-4 text-right font-mono tabular-nums font-medium ${
                    ret >= 0 ? 'text-emerald-400' : 'text-red-400'
                  }`}>
                    {ret >= 0 ? '+' : ''}{ret.toFixed(2)}%
                  </td>
                  <td className="py-2.5 pr-4 text-right font-mono text-tertiary tabular-nums">
                    {t.bars != null ? `${t.bars}d` : '—'}
                  </td>
                  <td className="py-2.5 text-right">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                      t.reason === 'TP' ? 'bg-emerald-500/10 text-emerald-400' :
                      t.reason === 'SL' ? 'bg-red-500/10 text-red-400' :
                      'bg-amber-500/10 text-amber-400'
                    }`}>
                      {t.reason ?? '—'}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
