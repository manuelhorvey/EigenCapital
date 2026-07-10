import React from 'react'
import { formatAssetPrice } from '../../utils/format'
import {
  governanceDot,
  governanceText,
  rrToState,
} from '../ui/governance'
import type { AssetCardInfo } from './types'
import PositionSparkline from './PositionSparkline'

interface Props {
  info: AssetCardInfo
}

/** Open position details for an asset card — side, entry, unrealized PnL, SL/TP distances, R:R ratio, and scale-out tiers. @param {{ info: AssetCardInfo }} props */
const AssetCardPosition = React.memo(({ info }: Props) => {
  const { position, risk } = info

  if (!position) return null

  const canShowSparkline =
    info.priceHistory != null &&
    info.priceHistory.length >= 4 &&
    info.positionEntry != null &&
    info.positionSide != null

  return (
    <div className="pt-2 border-t border-default/30 space-y-1.5 bg-surface/40 rounded-b-lg -mx-5 -mb-4 px-5 pb-4">
      <div className="flex items-center justify-between text-xs text-tertiary">
        <span className="flex items-center gap-1.5">
          <span
            className={`w-2 h-2 rounded-full ${
              position.side === 'long' ? governanceDot.GREEN : governanceDot.RED
            }`}
          />
          {position.side.toUpperCase()} @ ${formatAssetPrice(position.entry)}
          {position.layers && position.layers.length > 1 && (
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-accent-emerald/15 text-accent-emerald border border-accent-emerald/30 leading-none">
              ×{position.layers.length}
            </span>
          )}
        </span>
        {position.unrealized_pnl != null && (
          <span
            className={`font-mono ${
              position.unrealized_pnl >= 0 ? governanceText.GREEN : governanceText.RED
            }`}
          >
            {position.unrealized_pnl >= 0 ? '+' : ''}
            {position.unrealized_pnl.toFixed(2)} uPnL
          </span>
        )}
      </div>

      {risk && (
        <div className="flex items-center gap-x-3 text-xs">
          {position.tp != null && position.tp !== 0 && (
            <span className="flex items-center gap-1 text-tertiary">
              <span className={`w-1.5 h-1.5 rounded-full ${governanceDot.GREEN}`} />
              TP {formatAssetPrice(position.tp)}
              <span className={`font-mono ${governanceText.GREEN}`}>↑{risk.tpDistPct.toFixed(2)}%</span>
            </span>
          )}
          {position.sl != null && position.sl !== 0 && (
            <span className="flex items-center gap-1 text-tertiary">
              <span className={`w-1.5 h-1.5 rounded-full ${governanceDot.RED}`} />
              SL {formatAssetPrice(position.sl)}
              <span className={`font-mono ${governanceText.RED}`}>↓{risk.slDistPct.toFixed(2)}%</span>
            </span>
          )}
          {risk.rr > 0 && (
            <span className={`ml-auto font-mono font-semibold ${governanceText[rrToState(risk.rr)]}`}>
              {risk.rr.toFixed(1)}:1
            </span>
          )}
        </div>
      )}

      {canShowSparkline && info.positionSide && info.positionEntry != null && (
        <PositionSparkline
          prices={info.priceHistory!}
          entry={info.positionEntry}
          tp={info.positionTp}
          sl={info.positionSl}
          side={info.positionSide}
          height={32}
        />
      )}

      {info.scaleOutActive && info.scaleOutTiers && info.scaleOutTiers.length > 0 && (
        <div className="space-y-1">
          <div className="text-[10px] text-tertiary font-medium uppercase tracking-wider flex items-center gap-1">
            Scale-out tiers
            <span className="text-muted font-mono normal-case tracking-normal">
              ({info.remainingFraction != null ? (info.remainingFraction * 100).toFixed(0) : '?'}% remain)
            </span>
          </div>
          <div className="flex gap-1">
            {info.scaleOutTiers.map((tier, i) => (
              <div
                key={i}
                className={`flex-1 h-6 rounded text-[9px] font-mono flex items-center justify-center border ${
                  tier.filled
                    ? 'bg-gov-green/15 border-gov-green/40 text-gov-green'
                    : 'bg-panel border-default/50 text-tertiary'
                }`}
                title={`Tier ${i + 1}: ${(tier.fraction * 100).toFixed(0)}% @ $${tier.price}${
                  tier.filled
                    ? ` (filled @ $${tier.fill_price})`
                    : ' (pending)'
                }`}
              >
                {(tier.fraction * 100).toFixed(0)}%
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
})

AssetCardPosition.displayName = 'AssetCardPosition'

export default AssetCardPosition
