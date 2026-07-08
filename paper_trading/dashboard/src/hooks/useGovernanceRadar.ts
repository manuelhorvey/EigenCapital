import { useMemo } from 'react'
import { useSystemSnapshot } from './useSystemSnapshot'
import { systemSelectors } from '../selectors/system'

export interface RadarAxis {
  label: string
  value: number
  max: number
  description: string
}

export interface BottleneckEntry {
  rank: number
  layer: string
  avgPenalty: number
  assets: string[]
}

/** Derives governance radar axes and bottleneck rankings from the system snapshot. @returns {{ axes: RadarAxis[], bottlenecks: BottleneckEntry[], avgValidityImpact: number }} - Radar chart data and bottleneck analysis */
export function useGovernanceRadar(): {
  axes: RadarAxis[]
  bottlenecks: BottleneckEntry[]
  avgValidityImpact: number
} {
  const { data: snapshot } = useSystemSnapshot(systemSelectors.snapshot)
  const { data: health } = useSystemSnapshot(systemSelectors.health)
  const state = snapshot
  const seqId = snapshot?.sequence_id

  return useMemo(() => {
    // Compute exposure score (0-1, higher means governance allows more deployable exposure)
    const avgExp = state?.portfolio?.average_validity_exposure ?? 0
    const exposureScore = Math.min(1, Math.max(0, avgExp))

    // Compute feature stability (mean across assets)
    const assets = Object.values(state?.assets ?? {})
    const featStabilities = assets.map(a => a.feature_stability_jaccard ?? 0.5)
    const avgFeatStab = featStabilities.length
      ? featStabilities.reduce((a, b) => a + b, 0) / featStabilities.length
      : 0.5

    // Meta confidence
    const metaConfs = assets.map(a => a.meta_confidence ?? 0.5)
    const avgMetaConf = metaConfs.length
      ? metaConfs.reduce((a, b) => a + b, 0) / metaConfs.length
      : 0.5

    // Health-derived metrics
    const healthScores = health?.assets
      ? Object.values(health.assets).map(h => h.health_score)
      : []
    const avgHealth = healthScores.length
      ? healthScores.reduce((a, b) => a + b, 0) / healthScores.length
      : 0.5

    // PSI drift (0-1, higher is worse)
    const psiDrift = state?.halt_conditions?.prob_drift ?? 0
    const psiScore = Math.max(0, 1 - psiDrift * 2)

    // Drawdown control (0-1, higher is healthier) — asset drawdown is stored as negative percent.
    const worstDrawdownPct = assets.length
      ? Math.min(...assets.map(a => a.metrics?.drawdown ?? 0))
      : 0
    const drawdownLimitPct = Math.abs((state?.halt_conditions?.drawdown ?? -0.08) * 100)
    const drawdownUsage = drawdownLimitPct > 0 ? Math.abs(worstDrawdownPct) / drawdownLimitPct : 0
    const ddScore = Math.max(0, 1 - Math.min(1, drawdownUsage))

    const axes: RadarAxis[] = [
      { label: 'Exposure', value: exposureScore, max: 1, description: `Avg exposure ${(avgExp * 100).toFixed(0)}%` },
      { label: 'Feature Stability', value: avgFeatStab, max: 1, description: `Mean Jaccard ${(avgFeatStab * 100).toFixed(0)}%` },
      { label: 'Meta-Label', value: avgMetaConf, max: 1, description: `Mean confidence ${(avgMetaConf * 100).toFixed(0)}%` },
      { label: 'Health', value: avgHealth, max: 1, description: `System health ${(avgHealth * 100).toFixed(0)}%` },
      { label: 'PSI Drift', value: psiScore, max: 1, description: `Drift ${(psiDrift * 100).toFixed(0)}%` },
      { label: 'Drawdown Control', value: ddScore, max: 1, description: `Worst DD ${worstDrawdownPct.toFixed(2)}%` },
    ]

    // Bottleneck ranking
    const entries: { layer: string; penalty: number; assets: string[] }[] = []

    // PSI drift penalty
    if (psiDrift > 0.2) {
      const affected = assets
        .filter(a => a.validity_state === 'HALTED' || a.validity_state === 'RED')
        .map(a => a.metrics?.asset ?? '—')
      entries.push({
        layer: 'PSI Drift',
        penalty: -psiDrift * 0.5,
        assets: affected.length > 0 ? affected : ['SYSTEM'],
      })
    }

    // Exposure penalty
    if (avgExp < 0.85) {
      entries.push({
        layer: 'Exposure',
        penalty: -(0.85 - avgExp) * 0.4,
        assets: ['SYSTEM'],
      })
    }

    // Health penalty
    if (avgHealth < 0.8) {
      const weakAssets = health?.assets
        ? Object.entries(health.assets)
            .filter(([, h]) => h.health_score < 0.6)
            .map(([name]) => name)
        : []
      if (weakAssets.length > 0) {
        entries.push({
          layer: 'System Health',
          penalty: -(0.8 - avgHealth) * 0.6,
          assets: weakAssets,
        })
      }
    }

    // Drawdown penalty
    if (drawdownUsage > 0.75) {
      entries.push({
        layer: 'Drawdown',
        penalty: -drawdownUsage * 0.3,
        assets: ['SYSTEM'],
      })
    }

    const sorted = entries.sort((a, b) => a.penalty - b.penalty)
    const bottlenecks: BottleneckEntry[] = sorted.map((e, i) => ({
      rank: i + 1,
      layer: e.layer,
      avgPenalty: e.penalty,
      assets: e.assets.slice(0, 3),
    }))

    const avgPenalty = bottlenecks.length
      ? bottlenecks.reduce((s, b) => s + b.avgPenalty, 0) / bottlenecks.length
      : 0

    return { axes, bottlenecks, avgValidityImpact: avgPenalty }
  }, [seqId, state, health])
}
