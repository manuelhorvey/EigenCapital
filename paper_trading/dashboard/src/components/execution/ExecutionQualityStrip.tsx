import { useExecutionQuality } from '../../hooks/useExecutionQuality'
import Panel from '../ui/Panel'
import SectionHeader from '../ui/SectionHeader'
import KpiCard from '../ui/KpiCard'
import { Skeleton } from '../ui/Skeleton'

export default function ExecutionQualityStrip() {
  const { data, isPending } = useExecutionQuality()

  if (isPending) {
    return (
      <Panel>
        <SectionHeader title="Execution Quality" accent="blue" />
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
  const worstSlip = Math.max(...assets.map(a => byAsset[a].avg_entry_slippage_bps))
  const avgFill = assets.reduce((s, a) => s + byAsset[a].avg_fill_ratio, 0) / assets.length

  return (
    <Panel padding="md">
      <SectionHeader title="Execution Quality" accent="blue" />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard label="Avg EIS" value={(avgEis * 100).toFixed(1) + '%'} color={avgEis >= 0.7 ? 'text-gov-green' : 'text-gov-yellow'} />
        <KpiCard label="Avg FQI" value={(avgFqi * 100).toFixed(1) + '%'} color={avgFqi >= 0.8 ? 'text-gov-green' : 'text-gov-yellow'} />
        <KpiCard label="Worst Slippage" value={worstSlip.toFixed(1) + ' bps'} color={worstSlip > 10 ? 'text-gov-red' : 'text-gov-green'} />
        <KpiCard label="Fill Rate" value={(avgFill * 100).toFixed(1) + '%'} color={avgFill >= 0.95 ? 'text-gov-green' : 'text-gov-yellow'} />
      </div>
      <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-2xs text-tertiary">
        {assets.map(a => (
          <div key={a} className="flex items-center gap-1.5">
            <span className="font-mono font-medium text-secondary">{a}</span>
            <span>EIS={((byAsset[a].eis ?? 0) * 100).toFixed(0)}%</span>
            <span>FQI={((byAsset[a].fqi ?? 0) * 100).toFixed(0)}%</span>
          </div>
        ))}
      </div>
    </Panel>
  )
}
