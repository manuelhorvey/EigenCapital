/** One leg of an open position. */
export interface PositionLeg {
  entry: number
  side: 'long' | 'short'
  sl: number
  tp: number
  unrealized_pnl?: number | null
  layers?: unknown[]
}

/** A single scale-out tier. */
export interface ScaleOutTier {
  fraction: number
  price: number
  filled: boolean
  fill_price?: number
}

/** Computed risk geometry from a position + current price. */
export interface RiskGeometry {
  tpDistPct: number
  slDistPct: number
  rr: number
}

/** Badge selection metadata. */
export interface BadgeInfo {
  sellOnly: boolean
  tripwireActive: boolean
  isNew: boolean
  riskSignal?: { risk_level: string; risk_score: number } | null
  shadowAction?: { action_type: string } | null
}

/** Derived card data — returned by the parent useMemo. */
export interface AssetCardInfo {
  signal: string
  confidence: number
  price: number | null
  totalReturn: number
  drawdown: number
  meanConfidence: number
  nTrades: number
  nSignals: number
  position: PositionLeg | undefined
  risk: RiskGeometry | null
  signalDistribution: { BUY: number; SELL: number; FLAT: number } | undefined
  sellOnly: boolean
  tripwireActive: boolean
  slMult: number | null
  tpMult: number | null
  scaleOutActive: boolean
  scaleOutTiers: ScaleOutTier[] | null
  remainingFraction: number
  isNew: boolean
  riskSignal: { risk_level: string; risk_score: number } | null
  shadowAction: { action_type: string } | null
  /** Recent close prices since position opened, used to draw the position sparkline. */
  priceHistory: number[] | null
  /** Entry price of the open position (denormalized for sparkline anchor). */
  positionEntry: number | null
  /** Current TP of the open position, if any. */
  positionTp: number | null
  /** Current SL of the open position, if any. */
  positionSl: number | null
  /** Side of the open position, exposed for sparkline direction. */
  positionSide: 'long' | 'short' | null
}
