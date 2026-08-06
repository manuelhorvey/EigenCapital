import { memo, useCallback, useMemo } from 'react'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { useSelectedAsset } from '../hooks/useSelectedAsset'
import { confidenceToPercent } from '../utils/format'
import { assetHealth, healthColor } from '../utils/assetHealth'
import PositionBar from './ui/PositionBar'
import type { SystemBundle } from '../types/bundle'

interface Props {
  name: string
}

function signalColor(signal: string): string {
  switch (signal) {
    case 'BUY': return 'text-gov-green'
    case 'SELL': return 'text-gov-red'
    default: return 'text-gov-gray'
  }
}

function signalBg(signal: string): string {
  switch (signal) {
    case 'BUY': return 'bg-gov-green-muted border-gov-green/25'
    case 'SELL': return 'bg-gov-red-muted border-gov-red/25'
    default: return 'bg-gov-gray-muted border-gov-gray/20'
  }
}

function leftBar(signal: string): string {
  switch (signal) {
    case 'BUY': return 'bg-gov-green'
    case 'SELL': return 'bg-gov-red'
    default: return 'bg-gov-gray'
  }
}

function returnColor(v: number): string {
  if (v > 0) return 'text-gov-green'
  if (v < 0) return 'text-gov-red'
  return 'text-tertiary'
}

function SignalIcon({ signal }: { signal: string }) {
  if (signal === 'BUY') return <TrendingUp className="w-2.5 h-2.5" strokeWidth={2.5} />
  if (signal === 'SELL') return <TrendingDown className="w-2.5 h-2.5" strokeWidth={2.5} />
  return <Minus className="w-2.5 h-2.5" strokeWidth={2.5} />
}

function pricePrecision(price: number | undefined): number {
  return typeof price === 'number' && price < 10 ? 5 : 2
}

const AssetMiniCard = memo(function AssetMiniCard({ name }: Props) {
  const { data: asset } = useSystemSnapshot(
    useCallback((b: SystemBundle) => b.snapshot.assets?.[name], [name])
  )
  const { setSelectedAsset } = useSelectedAsset()

  const info = useMemo(() => {
    if (!asset) return null
    const m = asset.metrics
    const sig = asset.last_signal

    const signal: string =
      asset.final_signal ??
      (asset.sell_only && sig?.signal === 'BUY' ? 'FLAT' : sig?.signal) ??
      'FLAT'

    return {
      signal,
      confidence: confidenceToPercent(sig?.confidence),
      price: m.current_price ?? sig?.close_price,
      totalReturn: m.mtm_return ?? m.total_return ?? 0,
      drawdown: m.drawdown ?? 0,
      nTrades: m.n_trades ?? 0,
      sellOnly: asset.sell_only ?? false,
      tripwireActive: asset.tripwire_active ?? false,
      health: assetHealth(asset),
      position: m.position ?? null,
    }
  }, [asset])

  if (!info) return null

  const precision = pricePrecision(info.price)
  const pos = info.position
  const hasPos = !!pos && typeof pos.entry === 'number'

  return (
    <button
      type="button"
      onClick={() => setSelectedAsset(name)}
      className="group w-full text-left relative rounded-md border border-default bg-card overflow-hidden
        hover:border-strong hover:bg-panel transition-all duration-200 focus-ring active:scale-[0.99]"
      aria-label={`${name} — ${info.signal} @ ${info.price != null ? info.price.toFixed(precision) : '—'}`}
    >
      {/* Direction rail */}
      <span className={`absolute inset-y-0 left-0 w-0.5 ${leftBar(info.signal)}`} />

      <div className="p-2 pl-3">
        {/* Row 1: health dot + ticker + badges + signal */}
        <div className="flex items-center gap-1.5 min-w-0">
          <span className={`shrink-0 w-1.5 h-1.5 rounded-full ${healthColor[info.health]}`} title={`Health: ${info.health}`} />
          <span className="text-[11px] font-semibold text-primary truncate">{name}</span>
          {(info.sellOnly || info.tripwireActive) && (
            <span className={`shrink-0 text-[8px] font-bold px-1 py-px rounded-sm leading-none ${
              info.tripwireActive
                ? 'bg-gov-red-muted text-gov-red border border-gov-red/25'
                : 'bg-gov-yellow-muted text-gov-yellow border border-gov-yellow/25'
            }`}>
              {info.tripwireActive ? 'TRIP' : 'SO'}
            </span>
          )}
          <span className={`ml-auto shrink-0 inline-flex items-center gap-1 px-1 py-px rounded-sm border text-[9px] font-semibold ${signalBg(info.signal)} ${signalColor(info.signal)}`}>
            <SignalIcon signal={info.signal} />
            {info.signal}
          </span>
        </div>

        {/* Row 2: price + return */}
        <div className="flex items-baseline justify-between gap-2 mt-1">
          {info.price != null ? (
            <span className="text-[13px] font-mono font-semibold tabular-nums tracking-tight text-primary">
              {info.price.toFixed(precision)}
            </span>
          ) : (
            <span className="text-[13px] font-mono text-muted">—</span>
          )}
          <span className={`text-[11px] font-mono font-semibold tabular-nums ${returnColor(info.totalReturn)}`}>
            {info.totalReturn >= 0 ? '+' : ''}{info.totalReturn.toFixed(2)}%
          </span>
        </div>

        {/* Row 3: meta */}
        <div className="flex items-center justify-between gap-2 mt-0.5">
          <span className="text-[9px] font-mono tabular-nums text-tertiary">
            {info.confidence != null ? `${info.confidence}%ci` : '—'}
          </span>
          <span className="text-[9px] font-mono tabular-nums text-tertiary/70">
            {info.nTrades}tx · DD {info.drawdown.toFixed(1)}%
          </span>
        </div>

        {/* Position strip */}
        {hasPos && (
          <div className="mt-1.5 pt-1.5 border-t border-border/70">
            <div className="flex items-center justify-between text-2xs font-mono tabular-nums mb-1">
              <span className={`font-semibold ${pos.side === 'short' ? 'text-gov-red' : 'text-gov-green'}`}>
                {pos.side === 'short' ? 'SELL' : 'BUY'}
              </span>
              <span className={pos.unrealized_pnl >= 0 ? 'text-gov-green' : 'text-gov-red'}>
                {pos.unrealized_pnl >= 0 ? '+' : ''}{pos.unrealized_pnl.toFixed(0)} uPnL
              </span>
            </div>
            <PositionBar sl={pos.sl} tp={pos.tp} entry={pos.entry} current={info.price} side={pos.side} />
          </div>
        )}
      </div>
    </button>
  )
})

export default AssetMiniCard