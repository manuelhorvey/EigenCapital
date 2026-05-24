import React, { useMemo, useRef, useEffect, useState } from 'react'
import { usePortfolioState } from '../hooks/usePortfolioState'
import { formatAssetPrice } from '../utils/format'

interface Props {
  name: string
}

const AssetCard: React.FC<Props> = React.memo(({ name }) => {
  const { data } = usePortfolioState()
  const asset = data?.assets?.[name]

  const prevEntryRef = useRef<number | null>(null)
  const [newBadge, setNewBadge] = useState(false)

  const info = useMemo(() => {
    if (!asset) return null
    const m = asset.metrics
    const sig = asset.last_signal
    const pos = m.position
    const open = data?.open_positions?.[name]
    const hist = open?.prob_history ?? []
    const isNew = hist.length >= 2 && hist[hist.length - 1].signal !== hist[hist.length - 2].signal
    return {
      signal: sig?.signal ?? 'FLAT',
      confidence: sig?.confidence ?? 0,
      price: sig?.close_price,
      totalReturn: m.mtm_return ?? m.total_return ?? 0,
      drawdown: m.drawdown ?? 0,
      meanConf: m.mean_confidence ?? 0,
      nTrades: m.n_trades ?? 0,
      nSignals: m.n_signals ?? 0,
      pos,
      dist: m.signal_distribution,
      slMult: m.current_sl_mult ?? asset.sl_mult,
      tpMult: m.current_tp_mult ?? asset.tp_mult,
      scaleOutActive: m.scale_out_active ?? false,
      scaleOutTiers: m.scale_out_tiers ?? null,
      remainingFraction: m.remaining_fraction ?? 1,
      isNew,
    }
  }, [asset, data, name])

  useEffect(() => {
    const entry = info?.pos?.entry
    if (entry != null && entry !== prevEntryRef.current) {
      if (prevEntryRef.current !== null) {
        setNewBadge(true)
        const t = setTimeout(() => setNewBadge(false), 60_000)
        prevEntryRef.current = entry
        return () => clearTimeout(t)
      }
      prevEntryRef.current = entry
    }
  }, [info?.pos?.entry])

  if (!info) {
    return (
      <div className="panel rounded-lg px-4 py-3">
        <div className="text-sm text-secondary font-medium">{name}</div>
        <div className="text-xs text-tertiary mt-1">No data</div>
      </div>
    )
  }

  const confColor = info.confidence >= 60 ? 'text-gov-green' : info.confidence >= 45 ? 'text-gov-yellow' : 'text-gov-red'
  const retColor = info.totalReturn >= 0 ? 'text-gov-green' : 'text-gov-red'
  const ddColor = info.drawdown > -3 ? 'text-gov-green' : info.drawdown > -5 ? 'text-gov-yellow' : 'text-gov-red'

  return (
    <div className="relative panel rounded-lg px-4 py-3 panel-hover overflow-hidden group">
      <div className="flex items-center gap-2 mb-2">
        <span className="font-semibold text-sm text-primary">{name}</span>
        {(info.isNew || newBadge) && (
          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-gov-yellow-muted text-gov-yellow border border-gov-yellow/20 animate-pulse leading-none">
            NEW
          </span>
        )}
        {info.price != null && (
          <span className="text-xs text-tertiary font-mono ml-1">${formatAssetPrice(info.price)}</span>
        )}
        <span className="ml-auto flex items-center gap-2">
          <span className={`text-xs font-semibold ${info.signal === 'BUY' ? 'text-gov-green' : info.signal === 'SELL' ? 'text-gov-red' : 'text-muted'}`}>
            {info.signal}
          </span>
          <span className={`text-xs font-mono ${confColor}`}>{info.confidence.toFixed(0)}%</span>
        </span>
      </div>

      <div className="flex items-center gap-2 text-xs text-tertiary mb-2">
        <span className={retColor}>{info.totalReturn >= 0 ? '+' : ''}{info.totalReturn.toFixed(2)}%</span>
        <span className="text-default/50">|</span>
        <span className={ddColor}>DD {info.drawdown.toFixed(2)}%</span>
        <span className="text-default/50">|</span>
        <span>Conf {info.meanConf.toFixed(1)}%</span>
      </div>

      {info.slMult != null && info.tpMult != null && (
        <div className="flex items-center gap-2 text-xs text-tertiary mb-1">
          <span className="text-tertiary">SL <span className="font-mono text-gov-red/80">{info.slMult.toFixed(2)}x</span></span>
          <span className="text-muted">·</span>
          <span className="text-tertiary">TP <span className="font-mono text-gov-green/80">{info.tpMult.toFixed(2)}x</span></span>
          <span className="text-default/50">·</span>
          <span className="font-mono text-tertiary">{info.dist ? `${info.dist.BUY ?? 0}B ${info.dist.SELL ?? 0}S ${info.dist.FLAT ?? 0}F` : '—'}</span>
          <span className="ml-auto font-mono text-tertiary">{info.nSignals} sigs · {info.nTrades} trds</span>
        </div>
      )}

      {info.pos && (
        <div className="pt-2 border-t border-default/30">
          <div className="flex items-center justify-between text-xs text-tertiary">
            <span className="flex items-center gap-1.5">
              <span className={`w-2 h-2 rounded-full ${info.pos.side === 'long' ? 'bg-gov-green' : 'bg-gov-red'}`} />
              {info.pos.side.toUpperCase()} @ ${formatAssetPrice(info.pos.entry)}
            </span>
            <span className="font-mono">
              {info.pos.unrealized_pnl != null && (
                <span className={`${info.pos.unrealized_pnl >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
                  {info.pos.unrealized_pnl >= 0 ? '+' : ''}{info.pos.unrealized_pnl.toFixed(2)}%
                </span>
              )}
            </span>
          </div>
          <div className="flex items-center gap-2 text-xs mt-1">
            {(() => {
              const p = info.pos
              const isLong = p.side === 'long'
              const cur = info.price ?? p.entry
              const tpDist = isLong ? ((p.tp - cur) / cur) * 100 : ((cur - p.tp) / cur) * 100
              const slDist = isLong ? ((cur - p.sl) / cur) * 100 : ((p.sl - cur) / cur) * 100
              const reward = Math.abs(p.tp - p.entry)
              const risk = Math.abs(p.entry - p.sl)
              const rr = risk > 0 ? reward / risk : 0
              return (
                <>
                  {p.tp != null && p.tp !== 0 && (
                    <span className="flex items-center gap-1 text-tertiary">
                      <span className="w-1.5 h-1.5 rounded-full bg-gov-green" />
                      TP {formatAssetPrice(p.tp)}
                      <span className="text-gov-green font-mono">↑{tpDist.toFixed(2)}%</span>
                    </span>
                  )}
                  {p.sl != null && p.sl !== 0 && (
                    <span className="flex items-center gap-1 text-tertiary">
                      <span className="w-1.5 h-1.5 rounded-full bg-gov-red" />
                      SL {formatAssetPrice(p.sl)}
                      <span className="font-mono text-gov-red">↓{slDist.toFixed(2)}%</span>
                    </span>
                  )}
                  {rr > 0 && (
                    <span className={`ml-auto font-mono font-semibold ${rr >= 2 ? 'text-gov-green' : rr >= 1 ? 'text-gov-yellow' : 'text-gov-red'}`}>
                      {rr.toFixed(1)}:1
                    </span>
                  )}
                </>
              )
            })()}
          </div>

          {info.scaleOutActive && info.scaleOutTiers && info.scaleOutTiers.length > 0 && (
            <div className="mt-2 space-y-1">
              <div className="text-[10px] text-tertiary font-medium uppercase tracking-wider flex items-center gap-1">
                Scale-out Tiers
                <span className="text-muted font-mono normal-case tracking-normal">
                  ({info.remainingFraction != null ? (info.remainingFraction * 100).toFixed(0) : '?'}% remain)
                </span>
              </div>
              <div className="flex gap-1">
                {info.scaleOutTiers.map((tier, i) => {
                  const filled = tier.filled
                  const fillPct = tier.fraction * 100
                  return (
                    <div
                      key={i}
                      className={`flex-1 h-6 rounded text-[9px] font-mono flex items-center justify-center border transition-colors ${
                        filled
                          ? 'bg-gov-green/15 border-gov-green/40 text-gov-green'
                          : 'bg-panel border-default/50 text-tertiary'
                      }`}
                      title={`Tier ${i + 1}: ${fillPct.toFixed(0)}% @ $${tier.price}${filled ? ` (filled @ $${tier.fill_price})` : ' (pending)'}`}
                    >
                      {fillPct.toFixed(0)}%
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
})

AssetCard.displayName = 'AssetCard'
export default AssetCard
