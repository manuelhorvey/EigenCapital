import { useAttributionBundle } from '../../hooks/useAttributionBundle'
import Panel from '../ui/Panel'
import SectionHeader from '../ui/SectionHeader'
import { Skeleton } from '../ui/Skeleton'

/** A mono statistic cell — label uppercase tracking-wide + bold tabular-nums
 * value. Optional tone maps to governance semantic colors. */
function Stat({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: 'good' | 'warn' | 'bad'
}) {
  const cls =
    tone === 'good' ? 'text-gov-green'
    : tone === 'warn' ? 'text-gov-yellow'
    : tone === 'bad' ? 'text-gov-red'
    : 'text-primary'
  return (
    <div className="px-3 py-2 min-w-0">
      <p className="text-2xs text-tertiary uppercase tracking-wider truncate">{label}</p>
      <p className={`text-base font-bold font-mono tabular-nums ${cls} mt-0.5 truncate`}>{value}</p>
    </div>
  )
}

export default function ExecutionQualityStrip() {
  const { data: bundle, isPending } = useAttributionBundle()
  const data = bundle?.executionQuality

  if (isPending) {
    return (
      <Panel>
        <SectionHeader title="Execution Quality" accent="emerald" />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))}
        </div>
      </Panel>
    )
  }

  const byAsset = data?.by_asset ?? {}
  const assets = Object.keys(byAsset)
  if (assets.length === 0) return null

  const avgEis = assets.reduce((s, a) => s + (byAsset[a].eis ?? 0), 0) / assets.length
  const avgFqi = assets.reduce((s, a) => s + (byAsset[a].fqi ?? 0), 0) / assets.length
  const worstSlip = Math.max(...assets.map((a) => byAsset[a].avg_entry_slippage_bps))
  const avgFill = assets.reduce((s, a) => s + byAsset[a].avg_fill_ratio, 0) / assets.length

  return (
    <Panel padding="md">
      <SectionHeader title="Execution Quality" accent="emerald" />
      <div className="grid grid-cols-2 lg:grid-cols-4 lg:divide-x lg:divide-default -mx-3 border-b border-default">
        <Stat
          label="Avg EIS"
          value={`${(avgEis * 100).toFixed(1)}%`}
          tone={avgEis >= 0.7 ? 'good' : 'warn'}
        />
        <Stat
          label="Avg FQI"
          value={`${(avgFqi * 100).toFixed(1)}%`}
          tone={avgFqi >= 0.8 ? 'good' : 'warn'}
        />
        <Stat
          label="Worst Slippage"
          value={`${worstSlip.toFixed(1)} bps`}
          tone={worstSlip > 10 ? 'bad' : 'good'}
        />
        <Stat
          label="Fill Rate"
          value={`${(avgFill * 100).toFixed(1)}%`}
          tone={avgFill >= 0.95 ? 'good' : 'warn'}
        />
      </div>
      <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1 text-2xs text-tertiary font-mono">
        {assets.map((a) => (
          <div key={a} className="flex items-center gap-1.5">
            <span className="font-medium text-secondary">{a}</span>
            <span>EIS={((byAsset[a].eis ?? 0) * 100).toFixed(0)}%</span>
            <span>FQI={((byAsset[a].fqi ?? 0) * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </Panel>
  )
}
