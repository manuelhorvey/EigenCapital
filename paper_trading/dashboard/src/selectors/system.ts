import type { z } from 'zod'
import { SystemBundleSchema } from '../lib/schemas'

type SystemBundle = z.infer<typeof SystemBundleSchema>

export const systemSelectors = {
  snapshot: (b: SystemBundle) => b.snapshot,
  assets: (b: SystemBundle) => b.snapshot.assets,
  asset: (name: string) => (b: SystemBundle) => b.snapshot.assets?.[name] ?? null,
  portfolio: (b: SystemBundle) => b.snapshot.portfolio,
  engineStatus: (b: SystemBundle) => b.snapshot.engine_status,
  health: (b: SystemBundle) => b.live.health,
  mt5: (b: SystemBundle) => b.live.mt5,
}

/**
 * Factory that returns a selector for a single asset's state slot.
 * Combined with React Query's structural sharing, the returned reference
 * stays stable until that specific asset's data changes — preventing
 * unnecessary re-renders in components like AssetCard that previously
 * subscribed to the full snapshot.
 */
export function selectAsset(assetName: string) {
  return (b: SystemBundle) => b.snapshot.assets?.[assetName] ?? null
}

/** Selector for a single asset's open position (if any). */
export function selectOpenPosition(assetName: string) {
  return (b: SystemBundle) => b.snapshot.open_positions?.[assetName] ?? null
}

/** Selector for a single asset's risk signal (if any). */
export function selectRiskSignal(assetName: string) {
  return (b: SystemBundle) => b.snapshot.risk_signals?.[assetName] ?? null
}

/** Selector for a single asset's shadow action (if any). */
export function selectShadowAction(assetName: string) {
  return (b: SystemBundle) => b.snapshot.shadow_actions?.[assetName] ?? null
}

/**
 * Consolidated selector returning all AssetCard data in one pass.
 * Prevents 4 separate re-renders (asset, openPosition, riskSignal, shadowAction)
 * that occurred with individual selectors (audit finding).
 */
export function selectAssetCardBundle(assetName: string) {
  return (b: SystemBundle) => ({
    asset: b.snapshot.assets?.[assetName] ?? null,
    openPosition: b.snapshot.open_positions?.[assetName] ?? null,
    riskSignal: b.snapshot.risk_signals?.[assetName] ?? null,
    shadowAction: b.snapshot.shadow_actions?.[assetName] ?? null,
  })
}

/** Selector for the bundle meta (version, sequence_id, etc.). */
export const selectMeta = (b: SystemBundle) => b.meta
