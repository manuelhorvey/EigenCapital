import { Satellite } from 'lucide-react'
import { usePortfolioState } from '../hooks/usePortfolioState'

export default function SatelliteCard() {
  const { data } = usePortfolioState()
  const sat = data?.engine_status?.satellite

  if (!sat) {
    return (
      <div className="panel rounded-lg p-3">
        <div className="flex items-center gap-2 mb-1">
          <Satellite className="w-3.5 h-3.5 text-gov-yellow" strokeWidth={1.5} />
          <span className="text-2xs text-tertiary font-medium tracking-wide">BTC SATELLITE</span>
        </div>
        <div className="text-[11px] text-tertiary">Not initialized</div>
      </div>
    )
  }

  const ddColor = sat.drawdown_pct > -5 ? 'text-gov-green' : sat.drawdown_pct > -15 ? 'text-gov-yellow' : 'text-gov-red'
  const retColor = sat.total_return_pct >= 0 ? 'text-gov-green' : 'text-gov-red'
  const gateColor = sat.gate_open ? 'text-gov-green' : 'text-gov-yellow'
  const posColor = sat.position_active ? 'text-gov-green' : 'text-tertiary'

  return (
    <div className="panel rounded-lg p-3 panel-hover">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Satellite className="w-3.5 h-3.5 text-gov-amber" strokeWidth={1.5} />
          <span className="text-2xs text-tertiary font-medium tracking-wide">BTC SATELLITE</span>
        </div>
        <span className={`text-2xs font-mono font-semibold ${gateColor}`}>
          {sat.gate_open ? 'GATE OPEN' : 'GATE CLOSED'}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] mb-2">
        <div className="flex items-baseline justify-between">
          <span className="text-tertiary">Value</span>
          <span className={`font-mono font-semibold ${retColor}`}>
            ${sat.current_value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>
        <div className="flex items-baseline justify-between">
          <span className="text-tertiary">Return</span>
          <span className={`font-mono font-semibold ${retColor}`}>
            {sat.total_return_pct >= 0 ? '+' : ''}{sat.total_return_pct.toFixed(2)}%
          </span>
        </div>
        <div className="flex items-baseline justify-between">
          <span className="text-tertiary">DD</span>
          <span className={`font-mono font-semibold ${ddColor}`}>
            {sat.drawdown_pct.toFixed(2)}%
          </span>
        </div>
        <div className="flex items-baseline justify-between">
          <span className="text-tertiary">Alloc</span>
          <span className="font-mono font-semibold text-primary">
            {(sat.allocation_pct * 100).toFixed(1)}%
          </span>
        </div>
      </div>

      {sat.sharpe_contribution != null && (
        <div className="flex items-center justify-between text-2xs text-tertiary mb-1.5">
          <span>ΔSharpe (63d)</span>
          <span className={`font-mono font-semibold ${sat.sharpe_contribution >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
            {sat.sharpe_contribution >= 0 ? '+' : ''}{sat.sharpe_contribution.toFixed(2)}
          </span>
        </div>
      )}

      <div className="flex items-center gap-1.5 text-2xs">
        <span className={`w-1.5 h-1.5 rounded-full ${posColor}`} />
        <span className={posColor}>{sat.position_active ? 'POSITION ACTIVE' : 'NO POSITION'}</span>
      </div>

      {!sat.gate_open && sat.gate_reasons.length > 0 && (
        <div className="mt-1.5 pt-1.5 border-t border-default/30">
          <div className="text-2xs text-tertiary mb-0.5 font-medium">GATE BLOCKED:</div>
          {sat.gate_reasons.map((r, i) => (
            <div key={i} className="text-2xs text-gov-yellow/70 font-mono leading-tight">· {r}</div>
          ))}
        </div>
      )}
    </div>
  )
}
