import { useAttributionSummary } from '../../hooks/useAttributionSummary'
import Panel from '../ui/Panel'
import SectionHeader from '../ui/SectionHeader'
import KpiCard from '../ui/KpiCard'
import { Skeleton } from '../ui/Skeleton'

export default function AttributionBreakdownCard() {
  const { data, isPending } = useAttributionSummary()

  if (isPending) {
    return (
      <Panel>
        <SectionHeader title="Attribution Breakdown" accent="purple" />
        <div className="grid grid-cols-2 gap-3">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-12 rounded-lg" />)}
        </div>
      </Panel>
    )
  }

  const ds = data?.overall?.domain_scores
  if (!ds) return null

  return (
    <Panel padding="md">
      <SectionHeader title="Attribution Breakdown" accent="purple" meta={
        <span className="text-2xs text-tertiary">{data.overall.n_trades} trades</span>
      } />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <KpiCard label="Prediction" value={(ds.prediction_score * 100).toFixed(0) + '%'} color="text-accent-blue" />
        <KpiCard label="Execution" value={(ds.execution_score * 100).toFixed(0) + '%'} color="text-accent-purple" />
        <KpiCard label="Exit" value={(ds.exit_score * 100).toFixed(0) + '%'} color="text-gov-green" />
        <KpiCard label="Friction" value={(ds.friction_score * 100).toFixed(0) + '%'} color="text-gov-yellow" />
      </div>

      {/* Archetype breakdown */}
      {data.domain_scores && Object.keys(data.domain_scores).length > 0 && (
        <div className="mt-3">
          <p className="text-2xs font-medium text-tertiary mb-1">By Archetype</p>
          <div className="space-y-1">
            {Object.entries(data.domain_scores).map(([arch, scores]) => (
              <div key={arch} className="flex items-center gap-2 text-2xs">
                <span className="font-mono text-secondary w-24 shrink-0">{arch}</span>
                <span className="text-tertiary">P:{(scores.prediction_score * 100).toFixed(0)}%</span>
                <span className="text-tertiary">E:{(scores.execution_score * 100).toFixed(0)}%</span>
                <span className="text-tertiary">X:{(scores.exit_score * 100).toFixed(0)}%</span>
                <span className="text-tertiary">F:{(scores.friction_score * 100).toFixed(0)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Panel>
  )
}
