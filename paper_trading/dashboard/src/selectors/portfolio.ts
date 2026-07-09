import type { z } from 'zod'
import { SystemBundleSchema } from '../lib/schemas'

type SystemBundle = z.infer<typeof SystemBundleSchema>

export function selectAssetNames(bundle: SystemBundle | undefined): string[] {
  const assets = bundle?.snapshot?.assets
  if (!assets) return []
  return Object.keys(assets).sort()
}

export function selectPortfolioSummary(bundle: SystemBundle | undefined) {
  return bundle?.snapshot?.portfolio ?? null
}
