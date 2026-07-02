import React, { useMemo, useRef, useEffect, useState } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { useSelectedAsset } from '../hooks/useSelectedAsset'
import { confidenceToPercent, formatAssetPrice } from '../utils/format'
import {
  confToState,
  ddToState,
  rrToState,
  governanceDot,
  governanceText,
  governanceBorder,
  governanceBgMuted,
  type GovernanceState,
} from './ui/governance'

interface Props {
  name: string
  /** 'comfortable' = full detailed card; 'compact' = mini grid card */
  density?: 'comfortable' | 'compact'
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

interface PositionLeg {
  entry: number
  side: 'long' | 'short'
  sl: number
  tp: number
  unrealized_pnl?: number | null
  layers?: unknown[]
}

interface ScaleOutTier {
  fraction: number
  price: number
  filled: boolean
  fill_price?: number
}

interface RiskGeometry {
  tpDistPct: number
  slDistPct: number
  rr: number
}

interface BadgeInfo {
  sellOnly: boolean
  tripwireActive: boolean
  isNew: boolean
  riskSignal?: { risk_level: string; risk_score: number } | null
  shadowAction?: { action_type: string } | null
}

// One badge wins — tripwire beats sell-only beats risk-signal beats shadow-action beats "new".
function pickBadge(info: BadgeInfo) {
  if (info.tripwireActive) return { label: 'Tripwire', tone: 'red' as const, pulse: true }
  if (info.sellOnly) return { label: 'Sell only', tone: 'yellow' as const, pulse: false }
  if (info.riskSignal && info.riskSignal.risk_level === 'HIGH') return { label: 'Risk HIGH', tone: 'red' as const, pulse: false }
  if (info.shadowAction && info.shadowAction.action_type === 'PAUSE_TRADING') return { label: 'Shadow PAUSE', tone: 'red' as const, pulse: false }
  if (info.isNew) return { label: 'New', tone: 'yellow' as const, pulse: true }
  return null
}

function getRiskGeometry(pos: PositionLeg, currentPrice: number): RiskGeometry {
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

const AssetCard: React.FC<Props> = React.memo(({ name, density = 'comfortable' }) => {
  const { data: bundle } = useSystemSnapshot()
  const data = bundle?.snapshot
  const { setSelectedAsset } = useSelectedAsset()
  const asset = data?.assets?.[name]

  const prevEntryRef = useRef<number | null>(null)
  const [recentEntryBadge, setRecentEntryBadge] = useState(false)

  const info = useMemo(() => {
    if (!asset) return null

    const m = asset.metrics
    const sig = asset.last_signal
    const pos = m.position as PositionLeg | undefined
    const openPosition = data?.open_positions?.[name]
    const signalHistory = openPosition?.prob_history ?? []
    const isNew =
      signalHistory.length >= 2 &&
      signalHistory[signalHistory.length - 1].signal !== signalHistory[signalHistory.length - 2].signal

    const price = m.current_price ?? sig?.close_price
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
      riskSignal: (data?.risk_signals?.[name] ?? null) as { risk_level: string; risk_score: number } | null,
      shadowAction: (data?.shadow_actions?.[name] ?? null) as { action_type: string } | null,
    }
  }, [asset, data, name])

  // Flag a fresh entry for 60s so a re-render doesn't retrigger it on the
  // same position (only fires when entry price actually changes).
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
      <div className="bg-panel border border-default rounded-lg px-4 py-3 shadow-panel">
        <div className="text-sm text-secondary font-medium">{name}</div>
        <div className="text-xs text-tertiary mt-1">No data</div>
      </div>
    )
  }

  const confidenceState: GovernanceState = confToState(info.confidence)
  const returnState: GovernanceState = info.totalReturn >= 0 ? 'GREEN' : 'RED'
  const drawdownState: GovernanceState = ddToState(info.drawdown)
  const cardState: GovernanceState =
    info.signal === 'BUY' ? 'GREEN' : info.signal === 'SELL' ? 'RED' : 'INIT'
  const signalTextClass =
    info.signal === 'BUY' ? governanceText.GREEN : info.signal === 'SELL' ? governanceText.RED : 'text-muted'

  const badge = pickBadge({ sellOnly: info.sellOnly, tripwireActive: info.tripwireActive, isNew: info.isNew || recentEntryBadge, riskSignal: info.riskSignal, shadowAction: info.shadowAction })

  if (density === 'compact') {
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
      className={`relative bg-panel border border-default rounded-lg px-4 py-3 overflow-hidden shadow-panel transition-colors duration-150 hover:border-strong hover:shadow-card cursor-pointer border-l-2 active:scale-[0.98] sm:active:scale-100 ${governanceBorder[cardState]} ${governanceBgMuted[cardState]}`}
    >
      {/* Header: identity + signal. One badge max, price is secondary. */}
      <div className="flex items-center gap-2 mb-2">
        <span className="font-semibold text-sm text-primary">{name}</span>

        {badge && (
          <span
            className={`text-[10px] font-bold px-2 py-0.5 rounded-full leading-none border ${badge.tone === 'red'
                ? 'bg-gov-red-muted text-gov-red border-gov-red/20'
                : 'bg-gov-yellow-muted text-gov-yellow border-gov-yellow/20'
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
          <span className={`text-xs font-mono ${governanceText[confidenceState]}`}>
            {info.confidence.toFixed(0)}%
          </span>
        </span>
      </div>

      {/* Performance row: return, drawdown, mean confidence — even spacing, no mixed dividers */}
      <div className="flex items-center gap-x-3 text-xs text-tertiary mb-2">
        <span className={governanceText[returnState]}>
          {info.totalReturn >= 0 ? '+' : ''}
          {info.totalReturn.toFixed(2)}%
        </span>
        <span className={governanceText[drawdownState]}>DD {info.drawdown.toFixed(2)}%</span>
        <span>Conf {info.meanConfidence.toFixed(1)}%</span>
      </div>

      {/* Risk multipliers + signal mix — quiet, monochrome except SL/TP color cues */}
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

      {/* Open position block */}
      {info.position && (
        <div className="pt-2 border-t border-default/30">
          <div className="flex items-center justify-between text-xs text-tertiary">
            <span className="flex items-center gap-1.5">
              <span
                className={`w-2 h-2 rounded-full ${info.position.side === 'long' ? governanceDot.GREEN : governanceDot.RED
                  }`}
              />
              {info.position.side.toUpperCase()} @ ${formatAssetPrice(info.position.entry)}
              {info.position.layers && info.position.layers.length > 1 && (
                <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-accent-emerald/15 text-accent-emerald border border-accent-emerald/30 leading-none">
                  ×{info.position.layers.length}
                </span>
              )}
            </span>
            {info.position.unrealized_pnl != null && (
              <span
                className={`font-mono ${info.position.unrealized_pnl >= 0 ? governanceText.GREEN : governanceText.RED
                  }`}
              >
                {info.position.unrealized_pnl >= 0 ? '+' : ''}
                {info.position.unrealized_pnl.toFixed(2)} uPnL
              </span>
            )}
          </div>

          {info.risk && (
            <div className="flex items-center gap-x-3 text-xs mt-1">
              {info.position.tp != null && info.position.tp !== 0 && (
                <span className="flex items-center gap-1 text-tertiary">
                  <span className={`w-1.5 h-1.5 rounded-full ${governanceDot.GREEN}`} />
                  TP {formatAssetPrice(info.position.tp)}
                  <span className={`font-mono ${governanceText.GREEN}`}>↑{info.risk.tpDistPct.toFixed(2)}%</span>
                </span>
              )}
              {info.position.sl != null && info.position.sl !== 0 && (
                <span className="flex items-center gap-1 text-tertiary">
                  <span className={`w-1.5 h-1.5 rounded-full ${governanceDot.RED}`} />
                  SL {formatAssetPrice(info.position.sl)}
                  <span className={`font-mono ${governanceText.RED}`}>↓{info.risk.slDistPct.toFixed(2)}%</span>
                </span>
              )}
              {info.risk.rr > 0 && (
                <span className={`ml-auto font-mono font-semibold ${governanceText[rrToState(info.risk.rr)]}`}>
                  {info.risk.rr.toFixed(1)}:1
                </span>
              )}
            </div>
          )}

          {info.scaleOutActive && info.scaleOutTiers && info.scaleOutTiers.length > 0 && (
            <div className="mt-2 space-y-1">
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
                    className={`flex-1 h-6 rounded text-[9px] font-mono flex items-center justify-center border ${tier.filled
                        ? 'bg-gov-green/15 border-gov-green/40 text-gov-green'
                        : 'bg-panel border-default/50 text-tertiary'
                      }`}
                    title={`Tier ${i + 1}: ${(tier.fraction * 100).toFixed(0)}% @ $${tier.price}${tier.filled ? ` (filled @ $${tier.fill_price})` : ' (pending)'
                      }`}
                  >
                    {(tier.fraction * 100).toFixed(0)}%
                  </div>
                ))}
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