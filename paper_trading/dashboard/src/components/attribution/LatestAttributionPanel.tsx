import { useLatestAttribution } from '../../hooks/useLatestAttribution'

const LAYER_LABELS: Record<string, string> = {
  entry: 'Entry (model signal)',
  calibration: 'Calibration',
  exit: 'Exit (lifecycle)',
  profit_floor: 'Profit floor',
  portfolio: 'Portfolio sizing',
  risk: 'Risk controls',
}

const STATUS_COLORS: Record<string, string> = {
  APPLIED: '#22c55e',
  NOT_TRIGGERED: '#94a3b8',
  NOT_AVAILABLE: '#a3a3a3',
}

function formatR(value: number | null): string {
  if (value === null || value === undefined) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${(value as number).toFixed(2)}R`
}

export function LatestAttributionPanel() {
  const { data, error, isLoading } = useLatestAttribution()

  if (isLoading) {
    return <div className="text-sm text-slate-500">Loading latest attribution…</div>
  }

  if (error || !data) {
    return (
      <div className="text-sm text-slate-500 italic">
        No closed-trade attribution recorded yet. Attribution records are written
        to <code>data/live/latest_attribution.json</code> on every trade close.
      </div>
    )
  }

  const layers: Array<{ key: string; alpha: number | null; status: string }> = [
    { key: 'entry', alpha: data.entry_alpha_r, status: data.entry_alpha_status },
    { key: 'calibration', alpha: data.calibration_alpha_r, status: data.calibration_alpha_status },
    { key: 'exit', alpha: data.exit_alpha_r, status: data.exit_alpha_status },
    { key: 'profit_floor', alpha: data.profit_floor_alpha_r, status: data.profit_floor_alpha_status },
    { key: 'portfolio', alpha: data.portfolio_alpha_r, status: data.portfolio_alpha_status },
    { key: 'risk', alpha: data.risk_alpha_r, status: data.risk_alpha_status },
  ]

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900 p-4 text-slate-100">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-lg font-semibold">Last Closed-Trade Attribution</h3>
        <div className="text-xs text-slate-400">
          v{data.attribution_version} · {data.lifecycle_version}
        </div>
      </div>

      <div className="mb-3 grid grid-cols-2 gap-2 text-xs text-slate-400 sm:grid-cols-4">
        <div>
          <div className="uppercase">Asset</div>
          <div className="text-slate-100">{data.asset || '—'}</div>
        </div>
        <div>
          <div className="uppercase">Exit</div>
          <div className="text-slate-100">{data.exit_reason || '—'}</div>
        </div>
        <div>
          <div className="uppercase">Holding</div>
          <div className="text-slate-100">{data.holding_period_candles} bars</div>
        </div>
        <div>
          <div className="uppercase">Realized</div>
          <div className="text-slate-100">{formatR(data.realized_r)}</div>
        </div>
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-700 text-left text-xs uppercase text-slate-400">
            <th className="py-2">Layer</th>
            <th className="py-2 text-right">Alpha</th>
            <th className="py-2 text-right">Status</th>
          </tr>
        </thead>
        <tbody>
          {layers.map((layer) => (
            <tr key={layer.key} className="border-b border-slate-800">
              <td className="py-1.5">{LAYER_LABELS[layer.key] ?? layer.key}</td>
              <td className={`py-1.5 text-right font-mono ${(layer.alpha ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {formatR(layer.alpha)}
              </td>
              <td className="py-1.5 text-right">
                <span
                  className="rounded px-2 py-0.5 text-xs"
                  style={{
                    color: STATUS_COLORS[layer.status] ?? '#94a3b8',
                    borderColor: STATUS_COLORS[layer.status] ?? '#94a3b8',
                    borderWidth: 1,
                  }}
                >
                  {layer.status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {(data.static_exit_r !== null || data.no_profit_floor_r !== null) && (
        <div className="mt-3 rounded bg-slate-800 p-2 text-xs text-slate-400">
          <div className="font-semibold text-slate-200">Counterfactual Baselines</div>
          {data.static_exit_r !== null && (
            <div>
              Static TP R: <span className="font-mono">{formatR(data.static_exit_r)}</span>
              {data.static_exit_version && (
                <span className="ml-1 text-slate-500">({data.static_exit_version})</span>
              )}
            </div>
          )}
          {data.no_profit_floor_r !== null && (
            <div>
              No-floor R: <span className="font-mono">{formatR(data.no_profit_floor_r)}</span>
              {data.no_profit_floor_version && (
                <span className="ml-1 text-slate-500">({data.no_profit_floor_version})</span>
              )}
            </div>
          )}
          {data.uncalibrated_signal_r !== null && (
            <div>
              Uncalibrated R: <span className="font-mono">{formatR(data.uncalibrated_signal_r)}</span>
              {data.uncalibrated_signal_version && (
                <span className="ml-1 text-slate-500">({data.uncalibrated_signal_version})</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
