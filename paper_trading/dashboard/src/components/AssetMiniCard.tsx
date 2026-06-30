import { memo, useMemo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { useSelectedAsset } from '../hooks/useSelectedAsset'
import { confidenceToPercent } from '../utils/format'
import type { AssetState, Position, SignalDistribution } from '../types/portfolio'

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

function borderColor(signal: string): string {
  switch (signal) {
    case 'BUY': return 'border-l-gov-green'
    case 'SELL': return 'border-l-gov-red'
    default: return 'border-l-gov-gray'
  }
}

function returnColor(v: number): string {
  if (v > 0) return 'text-gov-green'
  if (v < 0) return 'text-gov-red'
  return 'text-tertiary'
}

function distributionBar(sd: SignalDistribution, total: number): string {
  if (total === 0) return ''
  const b = (sd.BUY / total * 100).toFixed(0)
  const s = (sd.SELL / total * 100).toFixed(0)
  const f = (sd.FLAT / total * 100).toFixed(0)
  return `${b}%/${s}%/${f}%`
}

const AssetMiniCard = memo(function AssetMiniCard({ name }: Props) {
  const { data: bundle } = useSystemSnapshot()
  const { setSelectedAsset } = useSelectedAsset()
  const asset: AssetState | undefined = bundle?.snapshot?.assets?.[name]

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
      signalDistribution: m.signal_distribution,
      sellOnly: asset.sell_only ?? false,
      tripwireActive: asset.tripwire_active ?? false,
      position: m.position ?? null,
    }
  }, [asset])

  if (!info) return null

  const sdTotal = info.signalDistribution
    ? info.signalDistribution.BUY + info.signalDistribution.SELL + info.signalDistribution.FLAT
    : 0

  return (
    <button
      type="button"
      onClick={() => setSelectedAsset(name)}
      className={`w-full text-left p-3 rounded-lg border border-default bg-surface
        hover:border-strong hover:bg-panel transition-all duration-200
        border-l-4 ${borderColor(info.signal)}
        focus-ring active:scale-[0.98]`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs font-semibold text-primary truncate">{name}</span>
          {(info.sellOnly || info.tripwireActive) && (
            <span className={`text-[9px] font-semibold px-1 py-0.5 rounded-sm leading-none ${
              info.tripwireActive
                ? 'bg-gov-red-muted text-gov-red border border-gov-red/25'
                : 'bg-gov-yellow-muted text-gov-yellow border border-gov-yellow/25'
            }`}>
              {info.tripwireActive ? '⚠' : 'SO'}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-sm border ${signalBg(info.signal)} ${signalColor(info.signal)}`}>
            {info.signal}
          </span>
          <span className={`text-[10px] font-mono tabular-nums ${signalColor(info.signal)}`}>
            {info.confidence}%
          </span>
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 mt-1.5">
        <div className="flex items-center gap-2 min-w-0">
          {info.price != null && (
            <span className="text-[10px] text-tertiary font-mono tabular-nums">
              ${info.price.toFixed(typeof info.price === 'number' && info.price < 10 ? 5 : 2)}
            </span>
          )}
          <span className={`text-[10px] font-mono tabular-nums ${returnColor(info.totalReturn)}`}>
            {info.totalReturn >= 0 ? '+' : ''}{info.totalReturn.toFixed(1)}%
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-[9px] text-tertiary font-mono tabular-nums">
            DD {info.drawdown.toFixed(1)}%
          </span>
          <span className="text-[9px] text-tertiary">
            {info.nTrades}tr
          </span>
        </div>
      </div>

      {info.position && (
        <div className="flex items-center gap-3 mt-1 text-[9px] font-mono tabular-nums text-tertiary">
          <span>SL <span className="text-gov-red">{info.position.sl.toFixed(typeof info.price === 'number' && info.price < 10 ? 5 : 2)}</span></span>
          <span>TP <span className="text-gov-green">{info.position.tp.toFixed(typeof info.price === 'number' && info.price < 10 ? 5 : 2)}</span></span>
        </div>
      )}
    </button>
  )
})

export default AssetMiniCard
