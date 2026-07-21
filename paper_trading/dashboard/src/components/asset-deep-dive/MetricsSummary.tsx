import { Activity } from 'lucide-react'

function pct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`
}

function MetricBox({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-surface rounded-lg px-3 py-2">
      <div className="text-2xs text-tertiary mb-0.5">{label}</div>
      <div className={`text-sm font-semibold font-mono tabular-nums ${color ?? 'text-primary'}`}>{value}</div>
    </div>
  )
}

export default function MetricsSummary({ metrics }: { metrics: Record<string, unknown> | null | undefined }) {
  const m = metrics ?? {}

  return (
    <div className="bg-panel rounded-lg border border-default p-4">
      <h3 className="text-xs font-semibold text-secondary mb-3 flex items-center gap-1.5">
        <Activity className="w-3.5 h-3.5" strokeWidth={1.5} />
        Key Metrics
      </h3>
      <div className="grid grid-cols-2 gap-3">
        <MetricBox label="Total Return" value={m.total_return != null ? `${(m.total_return as number) >= 0 ? '+' : ''}${(m.total_return as number).toFixed(1)}%` : '—'} color={(m.total_return as number) >= 0 ? 'text-signal-long' : 'text-signal-short'} />
        <MetricBox label="Drawdown" value={m.drawdown != null ? `${(m.drawdown as number).toFixed(1)}%` : '—'} color={(m.drawdown as number) < -5 ? 'text-signal-short' : ''} />
        <MetricBox label="Win Rate" value={pct(m.win_rate as number | null)} />
        <MetricBox label="Profit Factor" value={m.profit_factor != null ? (m.profit_factor as number).toFixed(2) : '—'} />
        <MetricBox label="Sharpe" value={m.sharpe_ratio != null ? (m.sharpe_ratio as number).toFixed(2) : '—'} />
        <MetricBox label="Trades" value={String(m.n_trades ?? 0)} />
        <MetricBox label="Avg Confidence" value={m.mean_confidence != null ? `${(m.mean_confidence as number).toFixed(1)}%` : '—'} />
      </div>
    </div>
  )
}