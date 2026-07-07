import { X, BarChart3, TrendingUp, TrendingDown, Activity } from 'lucide-react'
import { governanceText } from './ui/governance'
import { useAssetDeepDive } from '../hooks/useAssetDeepDive'

function pct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`
}

/**
 * Full-screen deep dive panel for a single asset. Shows feature importance, key metrics, MAE/MFE scatter, and trade history.
 * @param {{ name: string, onClose: () => void }} props
 */
/** Full-screen deep dive for a single asset: feature importance, metrics, MAE/MFE scatter, trade history.
 * @param {object} props
 * @param {string} props.name - Asset symbol
 * @param {() => void} props.onClose - Close handler */
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

  const fi = data.feature_importance ?? []
  const trades = data.trades ?? []
  const m = data.metrics ?? {}

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

          {/* ── Feature Importance ──────────────────────────────── */}
          <div className="bg-panel rounded-lg border border-default p-4">
            <h3 className="text-xs font-semibold text-secondary mb-3 flex items-center gap-1.5">
              <BarChart3 className="w-3.5 h-3.5" strokeWidth={1.5} />
              Feature Importance
            </h3>
            {fi.length === 0 || fi[0]?.error != null ? (
              <div className="text-xs text-tertiary">No feature importance available</div>
            ) : (
              <div className="space-y-1">
                {fi.slice(0, 15).map((f, fiIdx) => {
                  const imp = f.importance ?? 0
                  return (
                    <div key={f.feature ?? fiIdx} className="flex items-center gap-2">
                      <span className="text-xs text-tertiary w-2/3 truncate font-mono" title={f.feature}>{f.feature ?? '—'}</span>
                      <div className="flex-1 h-2 bg-surface rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full bg-accent-emerald"
                          style={{ width: `${(imp * 100).toFixed(1)}%` }}
                        />
                      </div>
                      <span className="text-2xs text-tertiary font-mono w-10 text-right">
                        {(imp * 100).toFixed(1)}%
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* ── Metrics Summary ─────────────────────────────────── */}
          <div className="bg-panel rounded-lg border border-default p-4">
            <h3 className="text-xs font-semibold text-secondary mb-3 flex items-center gap-1.5">
              <Activity className="w-3.5 h-3.5" strokeWidth={1.5} />
              Key Metrics
            </h3>
            <div className="grid grid-cols-2 gap-3">
              <MetricBox label="Total Return" value={m.total_return != null ? `${(m.total_return as number) >= 0 ? '+' : ''}${(m.total_return as number).toFixed(1)}%` : '—'} color={(m.total_return as number) >= 0 ? 'text-gov-green' : 'text-gov-red'} />
              <MetricBox label="Drawdown" value={m.drawdown != null ? `${(m.drawdown as number).toFixed(1)}%` : '—'} color={(m.drawdown as number) < -5 ? 'text-gov-red' : ''} />
              <MetricBox label="Win Rate" value={pct(m.win_rate as number | null)} />
              <MetricBox label="Profit Factor" value={m.profit_factor != null ? (m.profit_factor as number).toFixed(2) : '—'} />
              <MetricBox label="Sharpe" value={m.sharpe_ratio != null ? (m.sharpe_ratio as number).toFixed(2) : '—'} />
              <MetricBox label="Trades" value={String(m.n_trades ?? 0)} />
              <MetricBox label="Avg Confidence" value={m.mean_confidence != null ? `${(m.mean_confidence as number).toFixed(1)}%` : '—'} />
            </div>
          </div>

          {/* ── MAE/MFE Scatter ─────────────────────────────────── */}
          <div className="bg-panel rounded-lg border border-default p-4 xl:col-span-2">
            <h3 className="text-xs font-semibold text-secondary mb-3 flex items-center gap-1.5">
              <TrendingUp className="w-3.5 h-3.5" strokeWidth={1.5} />
              MAE / MFE Scatter
            </h3>
            {trades.length === 0 ? (
              <div className="text-xs text-tertiary text-center py-8">No trades yet</div>
            ) : (
              <>
                <div className="relative h-64 w-full">
                  <svg viewBox="0 0 400 400" className="w-full h-full" preserveAspectRatio="xMidYMid meet">
                    {/* Axes */}
                    <line x1="50" y1="350" x2="350" y2="350" stroke="var(--color-border)" strokeWidth="1" />
                    <line x1="50" y1="50" x2="50" y2="350" stroke="var(--color-border)" strokeWidth="1" />
                    {/* Diagonal perfect-trade line */}
                    <line x1="50" y1="350" x2="350" y2="50" stroke="var(--color-gov-green)" strokeWidth="0.5" strokeDasharray="4 4" opacity="0.3" />
                    {/* Points */}
                    const maxMae = Math.max(1, ...trades.map(t => Math.abs(t.mae ?? 0)))
                    const maxMfe = Math.max(1, ...trades.map(t => Math.abs(t.mfe ?? 0)))
                    // Scale the chart to the global max so no point is clipped.
                    const globalMax = Math.max(maxMae, maxMfe, 1)
                    {trades.map((t, i) => {
                      const mae = Math.abs(t.mae ?? 0)
                      const mfe = Math.abs(t.mfe ?? 0)
                      const x = 50 + ((mae / globalMax) * 280)
                      const y = 350 - ((mfe / globalMax) * 280)
                      const isWin = (t.return ?? 0) > 0
                      return (
                        <g key={i}>
                          <circle
                            cx={x}
                            cy={y}
                            r="5"
                            fill={isWin ? 'var(--color-gov-green)' : 'var(--color-gov-red)'}
                            opacity="0.7"
                          >
                            <title>{`${t.side} ${t.entry_date}: MAE=${mae.toFixed(1)}% MFE=${mfe.toFixed(1)}% R=${t.return?.toFixed(2) ?? '?'}`}</title>
                          </circle>
                        </g>
                      )
                    })}
                    {/* Axis labels */}
                    <text x="200" y="380" textAnchor="middle" fill="var(--color-text-tertiary)" fontSize="10" fontFamily="var(--font-mono)">MAE (adverse excursion %)</text>
                    <text x="20" y="200" textAnchor="middle" fill="var(--color-text-tertiary)" fontSize="10" fontFamily="var(--font-mono)" transform="rotate(-90, 20, 200)">MFE (favorable excursion %)</text>
                  </svg>
                </div>
                <div className="flex items-center gap-4 mt-2 text-2xs text-tertiary">
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-gov-green inline-block" /> Win</span>
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-gov-red inline-block" /> Loss</span>
                  <span className="text-muted">|</span>
                  <span>{trades.length} trades</span>
                </div>
              </>
            )}
          </div>

          {/* ── Trade History ───────────────────────────────────── */}
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

function MetricBox({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-surface rounded-lg px-3 py-2">
      <div className="text-2xs text-tertiary mb-0.5">{label}</div>
      <div className={`text-sm font-semibold font-mono tabular-nums ${color ?? 'text-primary'}`}>{value}</div>
    </div>
  )
}
