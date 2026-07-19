import React from 'react'
import {
  governanceText,
  ddToState,
  type GovernanceState,
} from '../ui/governance'
import type { AssetCardInfo } from './types'

interface AssetCardMetricsProps {
  info: AssetCardInfo
}

/** Performance metrics row for an asset card — return, drawdown, confidence, SL/TP multipliers, and signal mix. @param {{ info: AssetCardInfo }} props */
const AssetCardMetrics = React.memo(({ info }: AssetCardMetricsProps) => {
  const returnState: GovernanceState = info.totalReturn >= 0 ? 'GREEN' : 'RED'
  const drawdownState: GovernanceState = ddToState(info.drawdown)

  return (
    <>
      {/* Performance row */}
      <div className="flex items-center gap-x-3 text-xs text-tertiary mb-2">
        <span className={governanceText[returnState]}>
          {info.totalReturn >= 0 ? '+' : ''}
          {info.totalReturn.toFixed(2)}%
        </span>
        <span className={governanceText[drawdownState]}>DD {info.drawdown.toFixed(2)}%</span>
        <span>Conf {info.meanConfidence.toFixed(1)}%</span>
      </div>

      {/* Risk multipliers + signal mix */}
      {info.slMult != null && info.tpMult != null && (
        <div className="flex items-center gap-x-3 text-xs text-tertiary mb-1">
          <span>
            SL <span className="font-mono text-gov-red/80">{info.slMult.toFixed(2)}x</span>
          </span>
          <span>
            TP <span className="font-mono text-gov-green/80">{info.tpMult.toFixed(2)}x</span>
          </span>
          {info.signalDistribution && (
            <span className="font-mono">
              {info.signalDistribution.BUY ?? 0}B {info.signalDistribution.SELL ?? 0}S{' '}
              {info.signalDistribution.FLAT ?? 0}F
            </span>
          )}
          <span className="ml-auto font-mono">
            {info.nSignals} sigs · {info.nTrades} trades
          </span>
        </div>
      )}
    </>
  )
})

AssetCardMetrics.displayName = 'AssetCardMetrics'

export default AssetCardMetrics
