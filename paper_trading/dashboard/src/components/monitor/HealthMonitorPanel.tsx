import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../../lib/api'
import Panel from '../ui/Panel'
import StatCard from '../ui/StatCard'
import EmptyState from '../ui/EmptyState'

// ── Types ───────────────────────────────────────────────────────────────

interface UrgencyContributors {
  model_age: number
  psi_drift: number
  feature_stability: number
  inference_volume: number
}

interface UrgencyAsset {
  asset: string
  urgency_score: number
  contributors: UrgencyContributors
  limiting_factors: string[]
  needs_retrain: boolean
}

interface CheckGroup {
  n_assets: number
  results: unknown[]
}

interface HealthCheckReport {
  timestamp: string
  elapsed_s: number
  config: {
    max_age_days: number
    psi_threshold: number
    urgency_threshold: number
    urgency_weights: Record<string, number>
  }
  checks: {
    model_age: CheckGroup
    psi_baseline: CheckGroup
    feature_stability: CheckGroup
    inference_volume: CheckGroup
  }
  urgency: {
    n_assets: number
    mean_urgency: number
    max_urgency: number
    worst_asset: string
    n_needs_retrain: number
    assets: UrgencyAsset[]
  }
}

// ── Helpers ──────────────────────────────────────────────────────────────

function urgencyColor(score: number): string {
  if (score >= 0.8) return 'var(--color-gov-red)'
  if (score >= 0.5) return 'var(--color-gov-yellow)'
  if (score >= 0.3) return 'var(--color-accent-emerald)'
  return 'var(--color-text-tertiary)'
}

function urgencyLabel(score: number): string {
  if (score >= 0.8) return 'CRITICAL'
  if (score >= 0.5) return 'ELEVATED'
  if (score >= 0.3) return 'WATCH'
  return 'OK'
}

// ── Component ───────────────────────────────────────────────────────────

export default function HealthMonitorPanel() {
  const { data: report, isLoading } = useQuery<HealthCheckReport | { error: string }>({
    queryKey: ['healthcheck'],
    queryFn: () => fetchApi<HealthCheckReport | { error: string }>('/healthcheck.json'),
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 1,
  })

  const assets = useMemo(() => {
    if (!report || 'error' in report) return []
    return report.urgency.assets ?? []
  }, [report])

  const needsRetrain = useMemo(() => assets.filter(a => a.needs_retrain), [assets])

  if (isLoading) {
    return (
      <Panel padding="md">
        <EmptyState message="Loading model health data..." compact />
      </Panel>
    )
  }

  if (!report || 'error' in report) {
    return (
      <Panel padding="md">
        <EmptyState
          message={(report as { error?: string })?.error === 'not_found'
            ? 'No health check data yet — run scripts/ops/model_health_monitor.py first'
            : 'Model health data unavailable'}
          compact
        />
      </Panel>
    )
  }

  const u = report.urgency
  const elapsed = report.elapsed_s

  return (
    <div className="space-y-3">
      {/* Quick-stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <StatCard
          label="Mean Urgency"
          value={`${(u.mean_urgency * 100).toFixed(0)}%`}
          sub={u.n_assets > 0 ? `across ${u.n_assets} assets` : 'no data'}
          accent={urgencyColor(u.mean_urgency)}
          variant="compact"
        />
        <StatCard
          label="Max Urgency"
          value={`${(u.max_urgency * 100).toFixed(0)}%`}
          sub={u.worst_asset}
          accent={urgencyColor(u.max_urgency)}
          variant="compact"
        />
        <StatCard
          label="Needs Retrain"
          value={u.n_needs_retrain.toString()}
          sub={`threshold >${(report.config.urgency_threshold * 100).toFixed(0)}%`}
          accent={u.n_needs_retrain > 0 ? 'var(--color-gov-yellow)' : 'var(--color-gov-green)'}
          variant="compact"
        />
        <StatCard
          label="Status"
          value={urgencyLabel(u.max_urgency)}
          sub={elapsed ? `checked in ${(elapsed * 1000).toFixed(0)}ms` : ''}
          accent={urgencyColor(u.max_urgency)}
          variant="compact"
        />
      </div>

      {/* Retrain-needed alert */}
      {needsRetrain.length > 0 && (
        <Panel padding="md" variant="elevated">
          <div className="flex items-start gap-3">
            <span className="w-2 h-2 rounded-full mt-1 shrink-0 bg-gov-yellow" />
            <div className="min-w-0">
              <p className="text-xs font-semibold text-gov-yellow uppercase tracking-wider">
                Retrain Recommended
              </p>
              <p className="text-xs text-tertiary mt-1 break-words">
                {needsRetrain.map(a => (
                  <span key={a.asset} className="inline-flex items-center gap-1 mr-3">
                    <span className="font-mono font-medium">{a.asset}</span>
                    <span className="opacity-60">
                      ({a.limiting_factors.slice(0, 2).join(', ') || 'age'})
                    </span>
                  </span>
                ))}
              </p>
            </div>
          </div>
        </Panel>
      )}

      {/* Per-asset breakdown table */}
      {assets.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-2xs font-mono tabular-nums">
            <thead>
              <tr className="text-tertiary border-b border-default">
                <th className="text-left py-1.5 pr-3 font-medium uppercase tracking-wider">Asset</th>
                <th className="text-right py-1.5 px-2 font-medium uppercase tracking-wider">Urgency</th>
                <th className="text-right py-1.5 px-2 font-medium uppercase tracking-wider">Age</th>
                <th className="text-right py-1.5 px-2 font-medium uppercase tracking-wider">PSI</th>
                <th className="text-right py-1.5 px-2 font-medium uppercase tracking-wider">Stab</th>
                <th className="text-right py-1.5 px-2 font-medium uppercase tracking-wider">Vol</th>
                <th className="text-left py-1.5 pl-2 font-medium uppercase tracking-wider">Limiting</th>
              </tr>
            </thead>
            <tbody>
              {assets.map(a => {
                const c = a.contributors
                return (
                  <tr
                    key={a.asset}
                    className={`border-b border-default/50 hover:bg-panel/40 transition-colors ${
                      a.needs_retrain ? 'bg-gov-yellow-muted2/20' : ''
                    }`}
                  >
                    <td className="py-1.5 pr-3 font-medium">
                      <span className="flex items-center gap-1.5">
                        {a.needs_retrain && (
                          <span className="w-1.5 h-1.5 rounded-full bg-gov-yellow shrink-0" />
                        )}
                        {a.asset}
                      </span>
                    </td>
                    <td className="py-1.5 px-2 text-right font-semibold" style={{ color: urgencyColor(a.urgency_score) }}>
                      {(a.urgency_score * 100).toFixed(0)}%
                    </td>
                    <td className="py-1.5 px-2 text-right text-secondary">
                      {c.model_age > 0 ? `${(c.model_age * 100).toFixed(0)}%` : '—'}
                    </td>
                    <td className="py-1.5 px-2 text-right text-secondary">
                      {c.psi_drift > 0 ? `${(c.psi_drift * 100).toFixed(0)}%` : '—'}
                    </td>
                    <td className="py-1.5 px-2 text-right text-secondary">
                      {c.feature_stability > 0 ? `${(c.feature_stability * 100).toFixed(0)}%` : '—'}
                    </td>
                    <td className="py-1.5 px-2 text-right text-secondary">
                      {c.inference_volume > 0 ? `${(c.inference_volume * 100).toFixed(0)}%` : '—'}
                    </td>
                    <td className="py-1.5 pl-2 text-tertiary max-w-[160px] truncate">
                      {a.limiting_factors.length > 0
                        ? a.limiting_factors.slice(0, 2).join(', ')
                        : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
