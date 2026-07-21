import React from 'react'
import { formatAssetPrice } from '../../utils/format'
import { signalText, type GovernanceState } from '../ui/governance'
import type { AssetCardInfo } from './types'

interface BadgeDisplay {
  label: string
  tone: 'red' | 'yellow'
  pulse: boolean
}

interface AssetCardHeaderProps {
  name: string
  info: AssetCardInfo
  cardState: GovernanceState
  confidenceState: GovernanceState
  badge: BadgeDisplay | null
}

/**
 * Header row of an asset card. Renders name, status badge, current price, signal label, and confidence.
 * @param {{ name: string, info: AssetCardInfo, cardState: GovernanceState, confidenceState: GovernanceState, badge: BadgeDisplay | null }} props
 */
const AssetCardHeader = React.memo(({ name, info, cardState: _cardState, confidenceState, badge }: AssetCardHeaderProps) => {

  const signalTextClass =
    info.signal === 'BUY' ? signalText.LONG
    : info.signal === 'SELL' ? signalText.SHORT
    : 'text-muted'

  return (
    <div className="flex items-center gap-2 mb-2">
      <span className="font-semibold text-sm text-primary">{name}</span>

      {badge && (
        <span
          className={`text-[10px] font-bold px-2 py-0.5 rounded-full leading-none border ${
            badge.tone === 'red'
              ? 'bg-signal-short-muted text-signal-short border-signal-short/20'
              : 'bg-signal-warn-muted text-signal-warn border-signal-warn/20'
          } ${badge.pulse ? 'animate-pulse' : ''}`}
        >
          {badge.label}
        </span>
      )}

      {info.price != null && (
        <span className="text-xs text-tertiary font-mono ml-1">${formatAssetPrice(info.price)}</span>
      )}

      <span className="ml-auto flex items-baseline gap-2">
        <span className={`text-xs font-semibold ${signalTextClass}`}>{info.signal}</span>
        <span className={`text-xs font-mono ${signalText[confidenceState]}`}>
          {info.confidence.toFixed(0)}%
        </span>
      </span>
    </div>
  )
})

AssetCardHeader.displayName = 'AssetCardHeader'

export default AssetCardHeader
