import type { SystemBundle } from '../types/bundle'

export interface StatsRow {
  sharpe_ratio: number | null
  psr_gt_0: number | null
  psr_gt_1: number | null
  min_trl: number | null
  crs: number | null
  hhi: number | null
}

export type StatsData = Record<string, StatsRow>

export function selectStatisticalMetrics(bundle: SystemBundle | undefined): StatsData {
  const assets = bundle?.snapshot?.assets
  if (!assets) return {}

  const result: StatsData = {}
  for (const [name, asset] of Object.entries(assets)) {
    const m = asset.metrics
    result[name] = {
      sharpe_ratio: m.sharpe_ratio ?? null,
      psr_gt_0: m.psr_gt_0 ?? null,
      psr_gt_1: m.psr_gt_1 ?? null,
      min_trl: m.min_trl ?? null,
      crs: m.crs ?? null,
      hhi: m.hhi ?? null,
    }
  }
  return result
}
