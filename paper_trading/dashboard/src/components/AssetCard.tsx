import React, { useMemo } from 'react'
import { usePortfolioState } from '../hooks/usePortfolioState'
import { formatAssetPrice } from '../utils/format'

interface Props {
  name: string
}

function confidenceColor(c: number): string {
  if (c >= 60) return 'bg-emerald-500'
  if (c >= 45) return 'bg-amber-500'
  return 'bg-red-500'
}

const AssetCard: React.FC<Props> = React.memo(({ name }) => {
  const { data } = usePortfolioState()
  const asset = data?.assets?.[name]

  const info = useMemo(() => {
    if (!asset) return null
    const m = asset.metrics
    const sig = asset.last_signal
    const pos = m.position
    const signalClass = sig?.signal === 'BUY' ? 'signal-pill-buy' : sig?.signal === 'SELL' ? 'signal-pill-sell' : 'signal-pill-flat'
    const confColor = confidenceColor(sig?.confidence ?? 0)
    return {
      signal: sig?.signal ?? 'FLAT',
      confidence: sig?.confidence ?? 0,
      price: sig?.close_price,
      signalClass,
      confColor,
      totalReturn: m.mtm_return ?? m.total_return ?? 0,
      drawdown: m.drawdown ?? 0,
      meanConf: m.mean_confidence ?? 0,
      nTrades: m.n_trades ?? 0,
      nSignals: m.n_signals ?? 0,
      pos,
      dist: m.signal_distribution,
      currentValue: m.current_value ?? 0,
    }
  }, [asset])

  if (!info) {
    return (
      <div className="card-gradient card-border rounded-xl p-4">
        <div className="text-sm text-secondary font-medium">{name}</div>
        <div className="text-xs text-tertiary mt-2">No data</div>
      </div>
    )
  }

  return (
    <div className="relative card-gradient card-border rounded-xl p-4 hover-lift overflow-hidden group">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-sm text-primary">{name}</span>
          <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${
            info.signal === 'BUY' ? 'bg-emerald-500/10 text-emerald-400' :
            info.signal === 'SELL' ? 'bg-red-500/10 text-red-400' :
            'bg-amber-500/10 text-amber-400'
          }`}>
            {info.signal}
          </span>
        </div>
        {info.price != null && (
          <span className="text-xs text-tertiary font-mono">
            ${formatAssetPrice(info.price)}
          </span>
        )}
      </div>

      <div className="flex items-center gap-2 mb-3">
        <span className={`signal-pill ${info.signalClass}`}>
          {info.signal}
        </span>
        <div className="flex-1 conf-bar">
          <div className={`conf-bar-fill ${info.confColor}`} style={{ width: `${Math.min(info.confidence, 100)}%` }} />
        </div>
        <span className="text-[11px] text-tertiary font-mono w-10 text-right tabular-nums">
          {info.confidence.toFixed(1)}%
        </span>
      </div>

      <div className="grid grid-cols-3 gap-3 text-xs">
        {[
          { label: 'Return', value: info.totalReturn, color: info.totalReturn >= 0 ? 'text-emerald-400' : 'text-red-400', format: (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%` },
          { label: 'DD', value: info.drawdown, color: info.drawdown > -3 ? 'text-emerald-400' : info.drawdown > -5 ? 'text-amber-400' : 'text-red-400', format: (v: number) => `${v.toFixed(2)}%` },
          { label: 'Conf', value: info.meanConf, color: 'text-primary', format: (v: number) => `${v.toFixed(1)}%` },
        ].map(stat => (
          <div key={stat.label} className="bg-panel rounded-lg p-2">
            <div className="text-[10px] text-tertiary mb-0.5">{stat.label}</div>
            <div className={`font-mono text-[12px] font-medium ${stat.color}`}>
              {stat.format(stat.value)}
            </div>
          </div>
        ))}
      </div>

      {info.pos && (
        <div className="mt-2 pt-2 border-t border-default text-[11px] text-tertiary flex justify-between">
          <span className="flex items-center gap-1.5">
            <span className={`w-1.5 h-1.5 rounded-full ${info.pos.side === 'long' ? 'bg-emerald-500' : 'bg-red-500'}`} />
            {info.pos.side.toUpperCase()} @ ${formatAssetPrice(info.pos.entry)}
          </span>
          {info.pos.unrealized_pnl != null && (
            <span className={`font-mono ${info.pos.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {info.pos.unrealized_pnl >= 0 ? '+' : ''}{info.pos.unrealized_pnl.toFixed(2)}%
            </span>
          )}
        </div>
      )}

      <div className="mt-2 flex gap-2 text-[10px] text-tertiary">
        {info.dist && (
          <>
            <span className="text-emerald-500/70">{info.dist.BUY ?? 0}B</span>
            <span className="text-red-500/70">{info.dist.SELL ?? 0}S</span>
            <span className="text-amber-500/70">{info.dist.FLAT ?? 0}F</span>
          </>
        )}
        <span className="ml-auto text-tertiary">{info.nSignals} sigs · {info.nTrades} trades</span>
      </div>
    </div>
  )
})

AssetCard.displayName = 'AssetCard'
export default AssetCard
