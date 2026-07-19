import React, { useMemo, useRef, useEffect, useState } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { useSelectedAsset } from '../hooks/useSelectedAsset'
import { selectAssetCardBundle } from '../selectors/system'
import { confidenceToPercent } from '../utils/format'
import {
  confToState,
  governanceBorder,
  governanceBgMuted,
  type GovernanceState,
} from './ui/governance'
import type { PositionLeg, ScaleOutTier, AssetCardInfo } from './asset-card/types'
import AssetCardCompact from './asset-card/AssetCardCompact'
import AssetCardHeader from './asset-card/AssetCardHeader'
import AssetCardMetrics from './asset-card/AssetCardMetrics'
import AssetCardPosition from './asset-card/AssetCardPosition'

interface AssetCardProps {
  name: string
  /** 'comfortable' = full detailed card; 'compact' = mini grid card */
  density?: 'comfortable' | 'compact'
}

/** One badge wins — tripwire beats sell-only beats risk-signal beats shadow-action beats new. */
function pickBadge(badge: {
  sellOnly: boolean
  tripwireActive: boolean
  isNew: boolean
  riskSignal?: { risk_level: string; risk_score: number } | null
  shadowAction?: { action_type: string } | null
}) {
  if (badge.tripwireActive) return { label: 'Tripwire', tone: 'red' as const, pulse: true }
  if (badge.sellOnly) return { label: 'Sell only', tone: 'yellow' as const, pulse: false }
  if (badge.riskSignal && badge.riskSignal.risk_level === 'HIGH') return { label: 'Risk HIGH', tone: 'red' as const, pulse: false }
  if (badge.shadowAction && badge.shadowAction.action_type === 'PAUSE_TRADING') return { label: 'Shadow PAUSE', tone: 'red' as const, pulse: false }
  if (badge.isNew) return { label: 'New', tone: 'yellow' as const, pulse: true }
  return null
}

function getRiskGeometry(pos: PositionLeg, currentPrice: number): {
  tpDistPct: number
  slDistPct: number
  rr: number
} | null {
  const isLong = pos.side === 'long'
  const hasTp = pos.tp != null && pos.tp !== 0
  const hasSl = pos.sl != null && pos.sl !== 0

  const tpDistPct = hasTp
    ? (isLong ? (pos.tp - currentPrice) / currentPrice : (currentPrice - pos.tp) / currentPrice) * 100
    : 0
  const slDistPct = hasSl
    ? (isLong ? (currentPrice - pos.sl) / currentPrice : (pos.sl - currentPrice) / currentPrice) * 100
    : 0

  const reward = Math.abs(pos.tp - pos.entry)
  const risk = Math.abs(pos.entry - pos.sl)
  const rr = risk > 0 ? reward / risk : 0

  return { tpDistPct, slDistPct, rr }
}

/**
 * Per-asset card showing signal, confidence, price, metrics, and open position.
 * Supports comfortable (full detail) and compact (mini grid) densities.
 * @param {{ name: string, density?: 'comfortable' | 'compact' }} props
 */
const AssetCard: React.FC<AssetCardProps> = React.memo(({ name, density = 'comfortable' }) => {
  // Consolidated selector returns all AssetCard data in one pass, preventing
  // 4 separate re-renders per poll cycle (audit finding: selector consolidation).
  const { data: bundle } = useSystemSnapshot(selectAssetCardBundle(name))
  const asset = bundle?.asset ?? null
  const openPosition = bundle?.openPosition ?? null
  const riskSignal = bundle?.riskSignal ?? null
  const shadowAction = bundle?.shadowAction ?? null
  const { setSelectedAsset } = useSelectedAsset()

  const prevEntryRef = useRef<number | null>(null)
  const prevPositionEntryRef = useRef<number | null>(null)
  const [recentEntryBadge, setRecentEntryBadge] = useState(false)
  const [recentCloseBadge, setRecentCloseBadge] = useState(false)

  const info: AssetCardInfo | null = useMemo(() => {
    if (!asset) return null

    const m = asset.metrics
    const sig = asset.last_signal
    const pos = m.position as PositionLeg | undefined
    const signalHistory = openPosition?.prob_history ?? []
    const isNew =
      signalHistory.length >= 2 &&
      signalHistory[signalHistory.length - 1].signal !== signalHistory[signalHistory.length - 2].signal

    const price = (m.current_price ?? sig?.close_price) ?? null
    const risk = pos && price != null ? getRiskGeometry(pos, price) : null

    return {
      signal:
        asset.final_signal ??
        (pos?.side === 'long' ? 'BUY' : pos?.side === 'short' ? 'SELL' :
         asset.sell_only && sig?.signal === 'BUY' ? 'FLAT' : sig?.signal) ??
        'FLAT',
      confidence: confidenceToPercent(sig?.confidence),
      price,
      totalReturn: m.mtm_return ?? m.total_return ?? 0,
      drawdown: m.drawdown ?? 0,
      meanConfidence: confidenceToPercent(m.mean_confidence),
      nTrades: m.n_trades ?? 0,
      nSignals: m.n_signals ?? 0,
      position: pos,
      risk,
      signalDistribution: m.signal_distribution,
      sellOnly: asset.sell_only ?? false,
      tripwireActive: asset.tripwire_active ?? false,
      slMult: m.current_sl_mult ?? asset.sl_mult,
      tpMult: m.current_tp_mult ?? asset.tp_mult,
      scaleOutActive: m.scale_out_active ?? false,
      scaleOutTiers: (m.scale_out_tiers ?? null) as ScaleOutTier[] | null,
      remainingFraction: m.remaining_fraction ?? 1,
      isNew,
      riskSignal: (riskSignal ?? null) as { risk_level: string; risk_score: number } | null,
      shadowAction: (shadowAction ?? null) as { action_type: string } | null,
      priceHistory: pos
        ? signalHistory.map(p => p.close_price)
        : null,
      positionEntry: pos?.entry ?? null,
      positionTp: pos?.tp ?? null,
      positionSl: pos?.sl ?? null,
      positionSide: pos?.side ?? null,
    }
  }, [asset, name, openPosition, riskSignal, shadowAction])

  // Flag a position close for 60s — fires when position transitions from non-null to null.
  useEffect(() => {
    const positionEntry = info?.position?.entry
    if (positionEntry != null) {
      prevPositionEntryRef.current = positionEntry
      return
    }

    const wasOpen = prevPositionEntryRef.current != null
    prevPositionEntryRef.current = null
    if (!wasOpen) return

    setRecentCloseBadge(true)
    const timer = setTimeout(() => setRecentCloseBadge(false), 60_000)
    return () => clearTimeout(timer)
  }, [info?.position?.entry])

  // Flag a fresh entry for 60s — only fires when entry price actually changes.
  useEffect(() => {
    const entry = info?.position?.entry
    if (entry == null || entry === prevEntryRef.current) return

    const isFirstObservation = prevEntryRef.current === null
    prevEntryRef.current = entry
    if (isFirstObservation) return

    setRecentEntryBadge(true)
    const timer = setTimeout(() => setRecentEntryBadge(false), 60_000)
    return () => clearTimeout(timer)
  }, [info?.position?.entry])

  if (!info) {
    return (
      <div className="bg-panel border border-default rounded-lg px-5 py-4 shadow-panel">
        <div className="text-sm text-secondary font-medium">{name}</div>
        <div className="text-xs text-tertiary mt-1">No data</div>
      </div>
    )
  }

  const confidenceState: GovernanceState = confToState(info.confidence)
  const cardState: GovernanceState =
    info.signal === 'BUY' ? 'GREEN' : info.signal === 'SELL' ? 'RED' : 'INIT'

  if (density === 'compact') {
    return (
      <AssetCardCompact
        name={name}
        info={info}
        recentlyClosed={recentCloseBadge}
        onSelect={() => setSelectedAsset(name)}
      />
    )
  }

  // comfortable density (original rich card)
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => setSelectedAsset(name)}
      onKeyDown={(e: React.KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          setSelectedAsset(name)
        }
      }}
      className={`relative bg-panel border border-default rounded-lg px-5 py-4 overflow-hidden shadow-panel transition-colors duration-150 hover:border-strong hover:shadow-card cursor-pointer border-l-2 active:scale-[0.98] sm:active:scale-100 ${governanceBorder[cardState]} ${governanceBgMuted[cardState]}`}
    >
      <AssetCardHeader
        name={name}
        info={info}
        cardState={cardState}
        confidenceState={confidenceState}
        badge={pickBadge({
          sellOnly: info.sellOnly,
          tripwireActive: info.tripwireActive,
          isNew: info.isNew || recentEntryBadge,
          riskSignal: info.riskSignal,
          shadowAction: info.shadowAction,
        })}
      />
      <AssetCardMetrics info={info} />
      <AssetCardPosition info={info} />
    </div>
  )
})

AssetCard.displayName = 'AssetCard'

export default AssetCard
