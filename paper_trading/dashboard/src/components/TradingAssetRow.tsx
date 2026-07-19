import { memo, useCallback } from 'react'
import type { AssetTradingState } from '../lib/trading-state/types'
import { Info, CheckCircle2, FileDown } from 'lucide-react'

interface TradingAssetRowProps {
  asset: AssetTradingState
  onSelect?: (name: string) => void
}

function rowActionCls(visible: boolean) {
  return `p-1 rounded transition-all duration-100 ease-out ${
    visible
      ? 'opacity-100 pointer-events-auto'
      : 'opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto'
  }`
}

/** Compact terminal-precision asset row with direction, PnL, exit phase, risk, flags, and row-level actions. */
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

  const handleAction = useCallback((e: React.MouseEvent, action: string) => {
    e.stopPropagation()
    if (action === 'detail') onSelect?.(asset.identity)
  }, [asset.identity, onSelect])

  const handleExport = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    const csv = `Asset,Direction,PnL,Phase,Risk,Flags\n${asset.identity},${dir ?? 'N/A'},${pnl.toFixed(2)},${exit.phase},${risk.level},"${asset.flags.join(';')}"`
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${asset.identity}_trade.csv`
    a.click()
    URL.revokeObjectURL(url)
  }, [asset, dir, pnl, exit, risk])

  return (
    <div
      className="w-full flex items-center gap-2 py-1.5 px-2 border-b border-default/40 hover:bg-panel/40 transition-colors text-xs group"
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

      {/* Row-level actions — appear on hover */}
      <div className="flex items-center gap-0.5 shrink-0">
        <button
          onClick={(e) => handleAction(e, 'detail')}
          className={`${rowActionCls(false)} text-tertiary hover:text-primary`}
          title="Quick detail"
          aria-label={`Detail ${asset.identity}`}
        >
          <Info className="w-3 h-3" strokeWidth={1.5} />
        </button>
        <button
          onClick={(e) => handleAction(e, 'acknowledge')}
          className={`${rowActionCls(false)} text-tertiary hover:text-gov-green`}
          title="Acknowledge"
          aria-label={`Acknowledge ${asset.identity}`}
        >
          <CheckCircle2 className="w-3 h-3" strokeWidth={1.5} />
        </button>
        <button
          onClick={handleExport}
          className={`${rowActionCls(false)} text-tertiary hover:text-accent-blue`}
          title="Export trade"
          aria-label={`Export ${asset.identity} trade data`}
        >
          <FileDown className="w-3 h-3" strokeWidth={1.5} />
        </button>
      </div>
    </div>
  )
})
TradingAssetRow.displayName = 'TradingAssetRow'

export default TradingAssetRow
