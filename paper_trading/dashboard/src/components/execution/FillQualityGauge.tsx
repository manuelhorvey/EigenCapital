import { useExecutionQuality } from '../../hooks/useExecutionQuality'
import Panel from '../ui/Panel'
import SectionHeader from '../ui/SectionHeader'
import { Skeleton } from '../ui/Skeleton'

function Gauge({ label, value, size = 80 }: { label: string; value: number; size?: number }) {
  const pct = Math.min(Math.max(value, 0), 1)
  const color = pct >= 0.8 ? '#22c55e' : pct >= 0.5 ? '#f97316' : '#ef4444'
  const r = size * 0.35
  const circ = 2 * Math.PI * r
  const offset = circ * (1 - pct)

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#2a2a4a" strokeWidth={6} />
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke={color} strokeWidth={6}
          strokeDasharray={circ}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
        <text x={size / 2} y={size / 2} textAnchor="middle" dominantBaseline="central"
          fill="currentColor" fontSize={size * 0.18} fontWeight={600}
          className="text-secondary font-mono"
        >
          {(pct * 100).toFixed(0)}%
        </text>
      </svg>
      <span className="text-2xs text-tertiary">{label}</span>
    </div>
  )
}

export default function FillQualityGauge() {
  const { data, isPending } = useExecutionQuality()

  if (isPending) {
    return (
      <Panel>
        <SectionHeader title="Fill Quality" accent="purple" />
        <div className="flex gap-4 justify-center py-4">
          <Skeleton className="h-20 w-20 rounded-full" />
          <Skeleton className="h-20 w-20 rounded-full" />
        </div>
      </Panel>
    )
  }

  const byAsset = data?.by_asset ?? {}
  const assets = Object.keys(byAsset)
  if (assets.length === 0) return null

  const avgFqi = assets.reduce((s, a) => s + (byAsset[a].fqi ?? 0), 0) / assets.length
  const avgFillRatio = assets.reduce((s, a) => s + byAsset[a].avg_fill_ratio, 0) / assets.length

  return (
    <Panel padding="md">
      <SectionHeader title="Fill Quality" accent="purple" />
      <div className="flex items-center justify-center gap-6 py-2">
        <Gauge label="Avg FQI" value={avgFqi} />
        <Gauge label="Fill Ratio" value={avgFillRatio} />
      </div>
      <div className="grid grid-cols-2 gap-2 text-2xs text-tertiary mt-2">
        {assets.map(a => (
          <div key={a} className="flex justify-between">
            <span className="font-mono text-secondary">{a}</span>
            <span>FQI={((byAsset[a].fqi ?? 0) * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </Panel>
  )
}
