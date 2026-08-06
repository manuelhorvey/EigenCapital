import type { AssetState } from '../types/portfolio'

export type AssetHealth = 'healthy' | 'warning' | 'critical' | 'idle'

/**
 * Single source of truth for per-asset health. Used by the Overview's assets
 * health card, the individual asset cards, and the open positions grid so all
 * three stay in agreement about what a dot means.
 *
 * Rules (most severe wins):
 *  - halted or STRESSED liquidity      -> critical
 *  - any soft warning                  -> warning (governance/monitor noise)
 *  - sell-only guard armed             -> warning (reduced capability)
 *  - no trade record yet               -> idle (not "healthy", not "bad")
 *  - otherwise                         -> healthy
 */
export function assetHealth(asset: AssetState | undefined): AssetHealth {
  if (!asset) return 'idle'
  const m = asset.metrics
  if (asset.halt?.halted === true) return 'critical'
  if (asset.liquidity_regime === 'STRESSED') return 'critical'
  if (Array.isArray(asset.soft_warnings) && asset.soft_warnings.length > 0) return 'warning'
  if (asset.sell_only === true) return 'warning'
  if ((m?.n_trades ?? 0) === 0 && (m?.n_signals ?? 0) === 0) return 'idle'
  return 'healthy'
}

export const healthColor: Record<AssetHealth, string> = {
  healthy: 'bg-gov-green',
  warning: 'bg-gov-yellow',
  critical: 'bg-gov-red',
  idle: 'bg-gov-gray',
}

export const healthText: Record<AssetHealth, string> = {
  healthy: 'text-gov-green',
  warning: 'text-gov-yellow',
  critical: 'text-gov-red',
  idle: 'text-tertiary',
}

export const healthLabel: Record<AssetHealth, string> = {
  healthy: 'Healthy',
  warning: 'Watch',
  critical: 'At risk',
  idle: 'Idle',
}