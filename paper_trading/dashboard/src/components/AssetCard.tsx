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
    const open = data?.open_positions?.[name]
    const hist = open?.prob_history ?? []
    const isNew = hist.length >= 2 && hist[hist.length - 1].signal !== hist[hist.length - 2].signal
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
      isNew,
      slMult: asset.sl_mult,
      tpMult: asset.tp_mult,
    }
  }, [asset, data, name])

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
          {info.isNew && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 animate-pulse">
              NEW
            </span>
          )}
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

      {info.slMult != null && info.tpMult != null && (
        <div className="mt-2.5 bg-panel/30 border border-default/40 rounded-lg px-2.5 py-1.5 flex items-center justify-between text-[11px] text-tertiary">
          <span className="font-medium text-tertiary">Multipliers</span>
          <span className="font-mono text-secondary font-semibold">
            SL <span className="text-red-400">{info.slMult.toFixed(2)}x</span> · TP <span className="text-emerald-400">{info.tpMult.toFixed(2)}x</span>
          </span>
        </div>
      )}

      {info.pos && (
        <div className="mt-2 pt-2 border-t border-default space-y-1.5">
          <div className="flex justify-between text-[11px] text-tertiary">
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
          <div className="flex items-center gap-3 text-[10px]">
            {(() => {
              const isLong = info.pos!.side === 'long'
              const entry = info.pos!.entry
              const cur = info.price ?? entry
              const tpDist = isLong
                ? ((info.pos!.tp - cur) / cur) * 100
                : ((cur - info.pos!.tp) / cur) * 100
              const slDist = isLong
                ? ((cur - info.pos!.sl) / cur) * 100
                : ((info.pos!.sl - cur) / cur) * 100
              const reward = Math.abs(info.pos!.tp - entry)
              const risk = Math.abs(entry - info.pos!.sl)
              const rr = risk > 0 ? reward / risk : 0
              return (
                <>
                  {info.pos!.tp != null && info.pos!.tp !== 0 && (
                    <span className="flex items-center gap-1 text-tertiary">
                      <span className="w-1 h-1 rounded-full bg-emerald-500" />
                      TP {formatAssetPrice(info.pos!.tp)}
                      <span className="text-emerald-400 font-mono">
                        ↑{tpDist.toFixed(2)}%
                      </span>
                    </span>
                  )}
                  {info.pos!.sl != null && info.pos!.sl !== 0 && (
                    <span className="flex items-center gap-1 text-tertiary">
                      <span className="w-1 h-1 rounded-full bg-red-500" />
                      SL {formatAssetPrice(info.pos!.sl)}
                      <span className="font-mono text-red-400">
                        ↓{slDist.toFixed(2)}%
                      </span>
                    </span>
                  )}
                  {rr > 0 && (
                    <span className={`ml-auto font-mono font-semibold ${
                      rr >= 2 ? 'text-emerald-400' : rr >= 1 ? 'text-amber-400' : 'text-red-400'
                    }`}>
                      {rr.toFixed(1)}:1
                    </span>
                  )}
                </>
              )
            })()}
          </div>
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
