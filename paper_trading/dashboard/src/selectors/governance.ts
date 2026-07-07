import type { AssetState, EngineSnapshot } from '../types/portfolio'

/**
 * GovernanceState — mirror of the backend's governance computation.
 *
 * Historical context: this selector previously independently re-derived
 * combined_sl_mult and combined_size_scalar by multiplying regime ×
 * narrative × liquidity multipliers, applying its own floor/cap rules
 * (clamp at 0.30 floor, 10.0 ceiling) that did not match the backend.
 *
 * This was FAILURE MODE F6 — "selectors must be backend-mirrored, not
 * independently designed" (see FAILURE_MODES.md).
 *
 * Fix: read `combined_sl_mult`, `combined_size_scalar` and `floor_active`
 * from the AssetState, which the backend already computes in its own
 * governance pipeline. The selector is now a pure projection: it maps
 * backend fields to the GovernanceState shape without re-deriving.
 *
 * The backend fields `combined_sl_mult`, `combined_size_scalar`, and
 * `floor_active` are optional with defaults (1.0, 1.0, false) for
 * backward compatibility during deployment rollout.
 */
export interface GovernanceState {
  name: string
  validityState: string
  halted: boolean
  haltReasons: string[]
  softWarnings: string[]
  narrativeRegime: string | null
  narrativeStale: boolean
  liquidityRegime: string
  slMult: number
  sizeScalar: number
  floorActive: boolean
}

function extractAssetGovernance(name: string, asset: AssetState): GovernanceState {
  return {
    name,
    validityState: asset.validity_state,
    halted: asset.halt?.halted ?? false,
    haltReasons: asset.halt?.reasons ?? [],
    softWarnings: asset.soft_warnings ?? [],
    narrativeRegime: asset.narrative_regime,
    narrativeStale: asset.narrative_stale ?? false,
    liquidityRegime: asset.liquidity_regime,
    // Read the backend-computed combined values directly.
    // The backend already applies governance rules (regime × narrative × liquidity)
    // in its own pipeline. These fields are in the AssetState schema as optional
    // with defaults for rollout safety.
    slMult: asset.combined_sl_mult ?? 1.0,
    sizeScalar: asset.combined_size_scalar ?? 1.0,
    floorActive: asset.floor_active ?? false,
  }
}

export function selectGovernance(snapshot: EngineSnapshot): GovernanceState[] {
  const assets = snapshot.assets ?? {}
  return Object.entries(assets)
    .map(([name, asset]) => extractAssetGovernance(name, asset))
    .sort((a, b) => a.name.localeCompare(b.name))
}

export function selectGovernanceByAsset(
  snapshot: EngineSnapshot,
  assetName: string,
): GovernanceState | undefined {
  const asset = snapshot.assets?.[assetName]
  if (!asset) return undefined
  return extractAssetGovernance(assetName, asset)
}

export function selectGovernanceSummary(snapshot: EngineSnapshot): {
  total: number
  halted: number
  healthy: number
  floorActive: number
} {
  const states = selectGovernance(snapshot)
  return {
    total: states.length,
    halted: states.filter(s => s.halted).length,
    healthy: states.filter(s => s.validityState === 'GREEN' || s.validityState === 'YELLOW').length,
    floorActive: states.filter(s => s.floorActive).length,
  }
}
