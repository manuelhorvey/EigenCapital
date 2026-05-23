import { useHealthScores } from '../hooks/useHealthScores'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import { Skeleton } from './ui/Skeleton'
import { governanceBadge, healthColorToState } from './ui/governance'

const COMPONENT_LABELS: Record<string, string> = {
  validity: 'Validity',
  drift: 'Drift',
  pnl_stability: 'PnL Stability',
  shadow_agreement: 'Shadow Agreement',
  stress_robustness: 'Stress Robust.',
}

function barColor(score: number): string {
  if (score >= 0.8) return 'bg-gov-green'
  if (score >= 0.55) return 'bg-gov-yellow'
  return 'bg-gov-red'
}

export default function HealthScores() {
  const { data, isPending } = useHealthScores()

  if (isPending) {
    return (
      <Panel padding="md">
        <SectionHeader title="Asset Health" accent="purple" />
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-lg" />
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
        title="Asset Health"
        accent="purple"
        meta={
          <span className="text-2xs text-tertiary font-mono bg-panel px-2 py-0.5 rounded border border-default tabular-nums">
            Sys {((sys?.mean_health_score ?? 0) * 100).toFixed(0)}% · {sys?.n_healthy ?? 0} ok ·{' '}
            {sys?.n_degraded ?? 0} deg · {sys?.n_critical ?? 0} crit
          </span>
        }
      />

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-2">
        {names.map(name => {
          const h = data.assets[name]
          const state = healthColorToState(h.health_color)
          const badge = governanceBadge[state]
          const pct = (h.health_score * 100).toFixed(0)
          return (
            <div key={name} className={`border rounded-lg px-2.5 py-2 ${badge}`}>
              <div className="flex items-center justify-between mb-1 gap-1">
                <span className="text-xs font-semibold text-primary font-mono truncate">{name}</span>
                <span className="text-sm font-bold metric-value tabular-nums shrink-0">{pct}%</span>
              </div>
              <div className="w-full h-1 bg-panel rounded-full overflow-hidden mb-1.5">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${
                    state === 'GREEN' ? 'bg-gov-green' : state === 'YELLOW' ? 'bg-gov-yellow' : 'bg-gov-red'
                  }`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-2xs font-semibold uppercase tracking-wider opacity-90">
                {h.health_label}
              </span>
              <div className="mt-1.5 grid grid-cols-5 gap-0.5">
                {Object.entries(h.components).map(([key, val]) => (
                  <div
                    key={key}
                    className="flex flex-col items-center gap-0.5"
                    title={`${COMPONENT_LABELS[key] ?? key}: ${(val * 100).toFixed(0)}%`}
                  >
                    <div className="w-full h-3 bg-panel/80 rounded-sm overflow-hidden relative">
                      <div
                        className={`absolute bottom-0 left-0 right-0 ${barColor(val)} transition-all duration-500`}
                        style={{ height: `${val * 100}%` }}
                      />
                    </div>
                    <span className="text-[7px] text-muted uppercase tracking-tight leading-none font-mono">
                      {key === 'pnl_stability'
                        ? 'PnL'
                        : key === 'stress_robustness'
                          ? 'Str'
                          : key === 'shadow_agreement'
                            ? 'Shad'
                            : key.slice(0, 3)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </Panel>
  )
}
