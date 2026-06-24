import type { EngineSnapshot } from '../types/portfolio'
import type { SystemBundle } from '../types/bundle'

export function selectSnapshot(bundle: SystemBundle | undefined): EngineSnapshot | undefined {
  return bundle?.snapshot
}

export function selectAssetNames(bundle: SystemBundle | undefined): string[] {
  const assets = bundle?.snapshot?.assets
  if (!assets) return []
  return Object.keys(assets).sort()
}

export function selectPortfolioSummary(bundle: SystemBundle | undefined) {
  return bundle?.snapshot?.portfolio ?? null
}
