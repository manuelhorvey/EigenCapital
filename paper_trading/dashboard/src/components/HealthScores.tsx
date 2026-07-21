import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import { Skeleton } from './ui/Skeleton'
import { gridMetric6, GRID_GAP } from '../design/grid'

function healthColor(score: number): string {
  if (score >= 0.8) return 'bg-signal-long'
  if (score >= 0.5) return 'bg-signal-warn'
  return 'bg-signal-short'
}

function healthText(score: number): string {
  if (score >= 0.8) return 'text-signal-long'
  if (score >= 0.5) return 'text-signal-warn'
  return 'text-signal-short'
}

function healthBg(score: number): string {
  if (score >= 0.8) return 'bg-signal-long-muted2'
  if (score >= 0.5) return 'bg-signal-warn-muted2'
  return 'bg-signal-short-muted2'
}

function healthLabel(score: number): string {
  if (score >= 0.8) return 'Healthy'
  if (score >= 0.5) return 'Degraded'
  return 'Critical'
}

/** Per-asset health score grid with color-coded bars and healthy/degraded/critical labels. */
export default function HealthScores() {
  const { data, isPending } = useSystemSnapshot(systemSelectors.health)

  if (isPending) {
    return (
      <Panel padding="md">
        <SectionHeader title="System Health" accent="emerald" />
        <div className={`${gridMetric6()} ${GRID_GAP}`}>
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))}
        </div>
      </Panel>
    )
  }

  if (!data?.assets || Object.keys(data.assets).length === 0) return null

  const sys = data.system_health
  const names = Object.keys(data.assets).sort()

  return (
    <Panel padding="md">
      <SectionHeader
        title="System Health"
        accent="emerald"
        meta={
          <span className="text-[11px] text-tertiary font-mono bg-surface px-2 py-0.5 rounded border border-default tabular-nums">
            {sys?.n_healthy ?? 0} ok · {sys?.n_degraded ?? 0} deg · {sys?.n_critical ?? 0} crit
          </span>
        }
      />

      <div className={`${gridMetric6()} ${GRID_GAP}`}>
        {names.map(name => {
          const h = data.assets![name]
          const pct = (h.health_score * 100).toFixed(0)
          return (
            <div key={name} className={`border border-default rounded-lg px-3 py-2.5 ${healthBg(h.health_score)}`}>
              <div className="flex items-center justify-between gap-1 mb-2">
                <span className="text-xs font-semibold text-primary font-mono truncate">{name}</span>
                <span className={`text-sm font-bold metric-value tabular-nums shrink-0 ${healthText(h.health_score)}`}>
                  {pct}%
                </span>
              </div>
              <div className="w-full h-1.5 bg-panel rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${healthColor(h.health_score)}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <p className={`text-[11px] font-semibold uppercase tracking-wider mt-1.5 ${healthText(h.health_score)}`}>
                {healthLabel(h.health_score)}
              </p>
            </div>
          )
        })}
      </div>
    </Panel>
  )
}
