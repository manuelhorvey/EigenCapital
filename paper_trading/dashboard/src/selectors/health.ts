import type { z } from 'zod'
import { SystemBundleSchema } from '../lib/schemas'

type SystemBundle = z.infer<typeof SystemBundleSchema>

export interface SystemHealthSummary {
  assets: Record<string, { health_score: number; components: Record<string, number> }>
  system_health: {
    mean_health_score: number
    n_assets: number
    n_healthy: number
    n_degraded: number
    n_critical: number
    healthiest_asset: string
    weakest_asset: string
  }
}

export function selectHealthSummary(bundle: SystemBundle | undefined): SystemHealthSummary | null {
  const health = bundle?.live?.health
  if (!health || 'fetch_time' in health === false) return null
  const { assets, system_health } = health as unknown as SystemHealthSummary
  if (!assets || !system_health) return null
  return { assets, system_health }
}

export function selectHealthByAsset(
  bundle: SystemBundle | undefined,
  assetName: string,
): { health_score: number; components: Record<string, number> } | null {
  const summary = selectHealthSummary(bundle)
  if (!summary) return null
  return summary.assets[assetName] ?? null
}
