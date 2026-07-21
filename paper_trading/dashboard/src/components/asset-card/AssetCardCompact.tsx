import React from 'react'
import type { AssetCardInfo } from './types'
import PositionSparkline from './PositionSparkline'

interface AssetCardCompactProps {
  name: string
  info: AssetCardInfo
  recentlyClosed?: boolean
  onSelect: () => void
}

function signalColor(signal: string): string {
  switch (signal) {
    case 'BUY': return 'text-signal-long'
    case 'SELL': return 'text-signal-short'
    default: return 'text-signal-gray'
  }
}

function signalBg(signal: string): string {
  switch (signal) {
    case 'BUY': return 'bg-signal-long-muted border-signal-long/25'
    case 'SELL': return 'bg-signal-short-muted border-signal-short/25'
    default: return 'bg-signal-gray-muted border-signal-gray/20'
  }
}

function borderColor(signal: string): string {
  switch (signal) {
    case 'BUY': return 'border-l-signal-long'
    case 'SELL': return 'border-l-signal-short'
    default: return 'border-l-signal-gray'
  }
}

function returnColor(v: number): string {
  if (v > 0) return 'text-signal-long'
  if (v < 0) return 'text-signal-short'
  return 'text-tertiary'
}

/** Compact mini card for grid view — signal, confidence, price, return, drawdown, and SL/TP. @param {{ name: string, info: AssetCardInfo, recentlyClosed?: boolean, onSelect: () => void }} props */
const AssetCardCompact: React.FC<AssetCardCompactProps> = ({ name, info, recentlyClosed, onSelect }) => (
  <button
    type="button"
    onClick={onSelect}
    className={`w-full text-left p-4 rounded-lg border min-h-[112px] ${recentlyClosed          ? 'border-signal-gray/25 bg-surface/50' : 'border-default bg-surface'}
      hover:border-strong hover:bg-panel transition-all duration-200
      border-l-4 ${recentlyClosed          ? 'border-l-signal-gray/40' : borderColor(info.signal)}
      focus-ring active:scale-[0.98] ${recentlyClosed ? 'opacity-60' : ''}`}
  >
    <div className="flex items-center justify-between gap-2">
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-xs font-semibold text-primary truncate">{name}</span>
        {recentlyClosed && (
          <span className="text-[9px] font-semibold px-1 py-0.5 rounded-sm leading-none bg-signal-gray-muted text-signal-gray border border-signal-gray/25">
            Closed
          </span>
        )}
        {(info.sellOnly || info.tripwireActive) && (
          <span className={`text-[9px] font-semibold px-1 py-0.5 rounded-sm leading-none ${
            info.tripwireActive
              ? 'bg-signal-short-muted text-signal-short border border-signal-short/25'
              : 'bg-signal-warn-muted text-signal-warn border border-signal-warn/25'
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
        <span>SL <span className="text-signal-short">{info.position.sl.toFixed(typeof info.price === 'number' && info.price < 10 ? 5 : 2)}</span></span>
        <span>TP <span className="text-signal-long">{info.position.tp.toFixed(typeof info.price === 'number' && info.price < 10 ? 5 : 2)}</span></span>
      </div>
    )}
    {info.positionSide && info.priceHistory && info.priceHistory.length >= 4 && (
      <div className="mt-1.5">
        <PositionSparkline
          prices={info.priceHistory}
          entry={info.positionEntry!}
          tp={info.positionTp}
          sl={info.positionSl}
          side={info.positionSide}
          height={24}
        />
      </div>
    )}
  </button>
)

AssetCardCompact.displayName = 'AssetCardCompact'

export default AssetCardCompact
