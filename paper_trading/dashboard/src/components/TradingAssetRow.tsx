import { memo } from 'react'
import type { AssetTradingState } from '../lib/trading-state/types'

interface TradingAssetRowProps {
  asset: AssetTradingState
  onSelect?: (name: string) => void
}

/** Compact terminal-precision row: mono data, no badges, governance tones. */
const TradingAssetRow = memo(function TradingAssetRow({ asset, onSelect }: TradingAssetRowProps) {
  const dir = asset.direction
  const dirCls = dir === 'LONG' ? 'text-gov-green' : dir === 'SHORT' ? 'text-gov-red' : 'text-tertiary'

  const pnl = asset.pnl_state.unrealized
  const pnlCls = pnl >= 0 ? 'text-gov-green' : 'text-gov-red'
  const eff = asset.pnl_state.efficiency
  const effCls = eff === 'HIGH' ? 'text-gov-green' : eff === 'LOW' ? 'text-gov-red' : 'text-tertiary'

  const exit = asset.exit_state
  const phaseLabel = exit.phase === 'BREAKEVEN' ? 'BE'
    : exit.phase === 'TRAILING' ? 'Trail'
    : exit.phase === 'DECAY' ? 'Decay'
    : 'Static'
  const exitCls = exit.phase === 'TRAILING' ? 'text-gov-green'
    : exit.phase === 'BREAKEVEN' ? 'text-gov-yellow'
    : exit.phase === 'DECAY' ? 'text-gov-yellow'
    : 'text-tertiary'

  const risk = asset.risk_state
  const riskCls = risk.level === 'HIGH' ? 'text-gov-red'
    : risk.level === 'MEDIUM' ? 'text-gov-yellow'
    : 'text-gov-green'
  const driver = risk.drivers[0]

  return (
    <div
      onClick={() => onSelect?.(asset.identity)}
      className="w-full flex items-center gap-2 py-1.5 px-2 border-b border-default/40 hover:bg-panel/40 transition-colors cursor-pointer text-xs"
    >
      {/* Asset — name + direction char */}
      <div className="w-24 shrink-0 flex items-center gap-1 font-mono min-w-0">
        <span className="text-primary font-semibold truncate">{asset.identity}</span>
        {dir && <span className={`font-bold text-[10px] ${dirCls}`}>{dir === 'LONG' ? 'L' : 'S'}</span>}
      </div>

      {/* PnL — value + efficiency suffix */}
      <div className="w-20 shrink-0 text-right font-mono tabular-nums min-w-0">
        <span className={`font-semibold ${pnlCls}`}>{pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}</span>
        <span className={`text-[9px] ml-1 ${effCls}`}>{eff === 'HIGH' ? 'H' : eff === 'LOW' ? 'L' : 'N'}</span>
      </div>

      {/* Exit — compact phase + MFE */}
      <div className="w-36 shrink-0 font-mono tabular-nums min-w-0">
        <span className={`font-medium ${exitCls}`}>{phaseLabel}</span>
        {exit.peak_mfe_r != null && (
          <span className="text-tertiary ml-1">@ {exit.peak_mfe_r.toFixed(2)}R</span>
        )}
        {exit.sl_is_dynamic && <span className="text-tertiary/60 ml-0.5">✦</span>}
      </div>

      {/* Risk — level + driver */}
      <div className="w-24 shrink-0 min-w-0">
        <span className={`font-semibold ${riskCls}`}>{risk.level}</span>
        {driver && <span className="text-tertiary ml-1 text-[10px] truncate">{driver}</span>}
      </div>

      {/* Flags — compact text pills */}
      <div className="flex-1 flex items-center gap-1 min-w-0 justify-end">
        {asset.flags.slice(0, 2).map(f => (
          <span key={f} className="text-[10px] text-tertiary bg-surface/50 px-1.5 py-0.5 rounded leading-tight truncate max-w-[80px]">
            {f.replace(/_/g, ' ')}
          </span>
        ))}
      </div>
    </div>
  )
})

export default TradingAssetRow
