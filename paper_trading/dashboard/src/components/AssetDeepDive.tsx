import { X, TrendingDown } from 'lucide-react'
import { governanceText } from './ui/governance'
import { useAssetDeepDive } from '../hooks/useAssetDeepDive'
import FeatureImportanceChart from './asset-deep-dive/FeatureImportanceChart'
import MetricsSummary from './asset-deep-dive/MetricsSummary'
import MaeMfeScatter from './asset-deep-dive/MaeMfeScatter'

export default function AssetDeepDive({ name, onClose }: { name: string; onClose: () => void }) {
  const { data, isPending, isError } = useAssetDeepDive(name)

  if (isPending) {
    return (
      <div className="fixed inset-0 z-50 bg-app/95 flex items-center justify-center">
        <div className="text-sm text-tertiary animate-pulse">Loading {name}…</div>
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="fixed inset-0 z-50 bg-app/95 flex items-center justify-center">
        <div className="text-sm text-gov-red">Failed to load data for {name}</div>
        <button type="button" onClick={onClose} className="ml-3 text-xs text-tertiary hover:text-primary underline">Close</button>
      </div>
    )
  }

  const trades = data.trades ?? []

  return (
    <div className="fixed inset-0 z-50 bg-app/95 flex flex-col">
      <div className="flex items-center justify-between px-5 py-3 border-b border-default">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-bold text-primary">{data.asset}</h2>
          {data.sell_only && (
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
              data.tripwire_active
                ? 'bg-gov-red-muted text-gov-red border-gov-red/20 animate-pulse'
                : 'bg-gov-yellow-muted text-gov-yellow border-gov-yellow/20'
            }`}>
              {data.tripwire_active ? 'TRIPWIRE' : 'SELL-ONLY'}
            </span>
          )}
          <span className="text-xs font-mono text-tertiary">
            Signal: <span className={data.final_signal === 'BUY' ? governanceText.GREEN : data.final_signal === 'SELL' ? governanceText.RED : ''}>
              {data.final_signal ?? 'NONE'}
            </span>
          </span>
        </div>
        <button type="button" onClick={onClose} className="p-1.5 rounded-md hover:bg-panel transition-colors">
          <X className="w-5 h-5 text-secondary" strokeWidth={2} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <FeatureImportanceChart features={data.feature_importance ?? []} />
          <MetricsSummary metrics={data.metrics ?? {}} />

          <MaeMfeScatter trades={trades} />

          {/* Trade History */}
          <div className="bg-panel rounded-lg border border-default p-4 xl:col-span-2">
            <h3 className="text-xs font-semibold text-secondary mb-3 flex items-center gap-1.5">
              <TrendingDown className="w-3.5 h-3.5" strokeWidth={1.5} />
              Trade History
            </h3>
            {trades.length === 0 ? (
              <div className="text-xs text-tertiary text-center py-8">No trades yet</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-default">
                      <th className="table-header text-left py-2 pr-2">Date</th>
                      <th className="table-header text-left py-2 px-2">Side</th>
                      <th className="table-header text-right py-2 px-2">Entry</th>
                      <th className="table-header text-right py-2 px-2">Exit</th>
                      <th className="table-header text-right py-2 px-2">Return</th>
                      <th className="table-header text-right py-2 px-2">MAE%</th>
                      <th className="table-header text-right py-2 px-2">MFE%</th>
                      <th className="table-header text-left py-2 pl-2">Exit Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t, i) => (
                      <tr key={i} className="border-b border-default/40">
                        <td className="py-2 pr-2 text-tertiary font-mono tabular-nums">{t.exit_date?.split('T')[0] ?? t.entry_date?.split('T')[0] ?? ''}</td>
                        <td className="py-2 px-2">
                          <span className={t.side === 'long' ? governanceText.GREEN : governanceText.RED}>
                            {t.side?.toUpperCase() ?? '—'}
                          </span>
                        </td>
                        <td className="text-right py-2 px-2 font-mono tabular-nums text-secondary">{t.entry?.toFixed(4) ?? '—'}</td>
                        <td className="text-right py-2 px-2 font-mono tabular-nums text-secondary">{t.exit?.toFixed(4) ?? '—'}</td>
                        <td className={`text-right py-2 px-2 font-mono tabular-nums ${(t.return ?? 0) >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
                          {t.return != null ? `${t.return >= 0 ? '+' : ''}${t.return.toFixed(2)}R` : '—'}
                        </td>
                        <td className="text-right py-2 px-2 font-mono tabular-nums text-gov-red">{t.mae != null ? `${t.mae.toFixed(1)}%` : '—'}</td>
                        <td className="text-right py-2 px-2 font-mono tabular-nums text-gov-green">{t.mfe != null ? `${t.mfe.toFixed(1)}%` : '—'}</td>
                        <td className="py-2 pl-2 text-tertiary">{t.reason ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}