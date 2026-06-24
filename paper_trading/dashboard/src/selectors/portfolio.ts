import type { EngineSnapshot } from '../types/portfolio'
import type { SystemBundle } from '../types/bundle'

const MUTATION_SENTINEL = Symbol('qf-snapshot-guard')

function guardSnapshot(snapshot: EngineSnapshot | undefined): EngineSnapshot | undefined {
  if (!snapshot) return snapshot
  if (!(MUTATION_SENTINEL in snapshot)) {
    Object.defineProperty(snapshot, MUTATION_SENTINEL, { value: true, writable: false })
    Object.freeze(snapshot.assets)
  }
  return snapshot
}

export function selectSnapshot(bundle: SystemBundle | undefined): EngineSnapshot | undefined {
  return guardSnapshot(bundle?.snapshot)
}

export function selectAssetNames(bundle: SystemBundle | undefined): string[] {
  const assets = bundle?.snapshot?.assets
  if (!assets) return []
  return Object.keys(assets).sort()
}

export function selectPortfolioSummary(bundle: SystemBundle | undefined) {
  return bundle?.snapshot?.portfolio ?? null
}
