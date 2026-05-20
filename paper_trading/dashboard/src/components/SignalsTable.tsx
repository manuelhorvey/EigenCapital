import { useMemo } from 'react'
import { usePortfolioState } from '../hooks/usePortfolioState'
import { formatAssetPrice } from '../utils/format'

export default function SignalsTable() {
  const { data } = usePortfolioState()
  const rows = useMemo(() => {
    if (!data?.assets) return []
    return Object.entries(data.assets)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, asset]) => {
        const sig = asset.last_signal
        const m = asset.metrics
        const alloc = data.portfolio?.allocations?.[name] ?? 0
        return { name, sig, m, alloc }
      })
  }, [data])

  if (rows.length === 0) return null

  return (
    <div className="card-gradient card-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-emerald-500/50" />
          <h2 className="text-sm font-semibold text-primary">Signals</h2>
        </div>
        <span className="text-[11px] text-tertiary">{rows.length} assets</span>
      </div>
      <div className="overflow-x-auto -mx-4 px-4">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-default">
              <th className="table-header text-left py-2.5 pr-4">Asset</th>
              <th className="table-header text-left py-2.5 pr-4">Direction</th>
              <th className="table-header text-left py-2.5 pr-4">Signal</th>
              <th className="table-header text-right py-2.5 pr-4">Confidence</th>
              <th className="table-header text-right py-2.5 pr-4">Price</th>
              <th className="table-header text-right py-2.5 pr-4">Allocation</th>
              <th className="table-header text-right py-2.5 pr-4">Return</th>
              <th className="table-header text-right py-2.5">Drawdown</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ name, sig, m, alloc }, i) => (
              <tr
                key={name}
                className={`border-b border-default/50 transition-colors hover:bg-panel/50 ${
                  i % 2 === 0 ? '' : 'bg-panel/30'
                }`}
              >
                <td className="py-2.5 pr-4">
                  <span className="font-medium text-primary">{name}</span>
                </td>
                <td className="py-2.5 pr-4 text-secondary">
                  {sig?.signal === 'BUY' ? 'Bullish' : sig?.signal === 'SELL' ? 'Bearish' : 'Neutral'}
                </td>
                <td className="py-2.5 pr-4">
                  <span className={`signal-pill ${
                    sig?.signal === 'BUY' ? 'signal-pill-buy' : sig?.signal === 'SELL' ? 'signal-pill-sell' : 'signal-pill-flat'
                  }`}>
                    {sig?.signal ?? 'FLAT'}
                  </span>
                </td>
                <td className="py-2.5 pr-4">
                  <div className="flex items-center justify-end gap-2">
                    <div className="w-16 conf-bar">
                      <div
                        className={`conf-bar-fill ${
                          (sig?.confidence ?? 0) >= 60 ? 'bg-emerald-500' : (sig?.confidence ?? 0) >= 45 ? 'bg-amber-500' : 'bg-red-500'
                        }`}
                        style={{ width: `${Math.min(sig?.confidence ?? 0, 100)}%` }}
                      />
                    </div>
                    <span className="font-mono text-secondary w-10 text-right tabular-nums">
                      {(sig?.confidence ?? 0).toFixed(1)}%
                    </span>
                  </div>
                </td>
                <td className="py-2.5 pr-4 text-right font-mono text-secondary tabular-nums">
                  {formatAssetPrice(sig?.close_price)}
                </td>
                <td className="py-2.5 pr-4 text-right">
                  <div className="flex items-center justify-end gap-1.5">
                    <div className="w-12 conf-bar">
                      <div className="conf-bar-fill bg-blue-500/50" style={{ width: `${alloc * 100}%` }} />
                    </div>
                    <span className="font-mono text-tertiary w-9 text-right tabular-nums">
                      {(alloc * 100).toFixed(0)}%
                    </span>
                  </div>
                </td>
                <td className={`py-2.5 pr-4 text-right font-mono tabular-nums ${
                  (m?.mtm_return ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'
                }`}>
                  {(m?.mtm_return ?? 0).toFixed(2)}%
                </td>
                <td className={`py-2.5 text-right font-mono tabular-nums ${
                  (m?.drawdown ?? 0) > -3 ? 'text-emerald-400' : (m?.drawdown ?? 0) > -5 ? 'text-amber-400' : 'text-red-400'
                }`}>
                  {(m?.drawdown ?? 0).toFixed(2)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
