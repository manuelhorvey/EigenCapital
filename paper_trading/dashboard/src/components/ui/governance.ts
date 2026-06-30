/** Calibration / governance state — use everywhere for consistent color psychology */

export type GovernanceState = 'GREEN' | 'YELLOW' | 'RED' | 'INIT' | 'GRAY'

export const GOVERNANCE_STATES: GovernanceState[] = ['GREEN', 'YELLOW', 'RED', 'INIT', 'GRAY']

export const governanceBadge: Record<GovernanceState, string> = {
  GREEN: 'bg-gov-green-muted text-gov-green border-gov-green/25',
  YELLOW: 'bg-gov-yellow-muted text-gov-yellow border-gov-yellow/25',
  RED: 'bg-gov-red-muted text-gov-red border-gov-red/25',
  INIT: 'bg-gov-init-muted text-gov-init border-gov-init/25',
  GRAY: 'bg-gov-gray-muted text-gov-gray border-gov-gray/25',
}

export const governanceDot: Record<GovernanceState, string> = {
  GREEN: 'bg-gov-green',
  YELLOW: 'bg-gov-yellow',
  RED: 'bg-gov-red',
  INIT: 'bg-gov-init',
  GRAY: 'bg-gov-gray',
}

export const governanceText: Record<GovernanceState, string> = {
  GREEN: 'text-gov-green',
  YELLOW: 'text-gov-yellow',
  RED: 'text-gov-red',
  INIT: 'text-gov-init',
  GRAY: 'text-gov-gray',
}

export const governanceBorder: Record<GovernanceState, string> = {
  GREEN: 'border-l-gov-green',
  YELLOW: 'border-l-gov-yellow',
  RED: 'border-l-gov-red',
  INIT: 'border-l-gov-init',
  GRAY: 'border-l-gov-gray',
}

export const governanceBgMuted: Record<GovernanceState, string> = {
  GREEN: 'bg-gov-green-muted2',
  YELLOW: 'bg-gov-yellow-muted2',
  RED: 'bg-gov-red-muted2',
  INIT: 'bg-gov-init-muted2',
  GRAY: 'bg-gov-gray-muted2',
}

export function prematureRateState(rate: number | null): GovernanceState {
  if (rate === null) return 'INIT'
  if (rate > 0.3) return 'RED'
  if (rate > 0.1) return 'YELLOW'
  return 'GREEN'
}

export function scalarToState(value: number): GovernanceState {
  if (value >= 1.0) return 'GREEN'
  if (value > 0.7) return 'YELLOW'
  return 'RED'
}

export function regimeToState(regime: string): GovernanceState {
  if (regime === 'STRESSED') return 'RED'
  if (regime === 'THIN') return 'YELLOW'
  return 'GREEN'
}

export function narrRegimeToState(regime: string | null): GovernanceState | null {
  if (!regime) return null
  if (regime === 'risk_off') return 'RED'
  if (regime === 'geopol_tension') return 'YELLOW'
  if (regime === 'risk_on') return 'GREEN'
  return null
}

export function validityToState(state: string): GovernanceState {
  const s = state.toLowerCase()
  if (s === 'green') return 'GREEN'
  if (s === 'yellow' || s === 'amber') return 'YELLOW'
  if (s === 'red') return 'RED'
  return 'INIT'
}

export function scoreToState(score: number): GovernanceState {
  if (score >= 0.8) return 'GREEN'
  if (score >= 0.5) return 'YELLOW'
  return 'RED'
}

export function confToState(confidence: number): GovernanceState {
  const pct = Math.min(100, Math.max(0, confidence <= 1 ? confidence * 100 : confidence))
  if (pct >= 60) return 'GREEN'
  if (pct >= 45) return 'YELLOW'
  return 'RED'
}

export function rrToState(rr: number): GovernanceState {
  if (rr >= 2) return 'GREEN'
  if (rr >= 1) return 'YELLOW'
  return 'RED'
}

export function ddToState(drawdown: number): GovernanceState {
  if (drawdown > -3) return 'GREEN'
  if (drawdown > -5) return 'YELLOW'
  return 'RED'
}

export function healthColorToState(color: string): GovernanceState {
  if (color === 'green') return 'GREEN'
  if (color === 'amber') return 'YELLOW'
  if (color === 'red') return 'RED'
  return 'INIT'
}

/* ── State meta system (PR1) ────────────────────────────── */

export interface GovStateMeta {
  fill: string
  border: string
  dot: string
  motion: string
}

export const GOV_STATE_META: Record<GovernanceState, GovStateMeta> = {
  GREEN:  { fill: 'bg-gov-green text-white',               border: 'border-gov-green/25 bg-gov-green-muted text-gov-green', dot: 'bg-gov-green',  motion: '' },
  YELLOW: { fill: 'bg-gov-yellow text-white',              border: 'border-gov-yellow/25 bg-gov-yellow-muted text-gov-yellow', dot: 'bg-gov-yellow', motion: 'animate-pulse-subtle' },
  RED:    { fill: 'bg-gov-red text-white',                 border: 'border-gov-red/25 bg-gov-red-muted text-gov-red',       dot: 'bg-gov-red',    motion: 'state-pulse-red' },
  INIT:   { fill: 'bg-gov-init text-white',                border: 'border-gov-init/25 bg-gov-init-muted text-gov-init',    dot: 'bg-gov-init',   motion: '' },
  GRAY:   { fill: 'bg-gov-gray text-white',                border: 'border-gov-gray/25 bg-gov-gray-muted text-gov-gray',    dot: 'bg-gov-gray',   motion: '' },
}

export function getStateMeta(state: GovernanceState): GovStateMeta {
  return GOV_STATE_META[state]
}

export function mapStateToFill(state: GovernanceState): string {
  return GOV_STATE_META[state].fill
}

export function mapStateToBorder(state: GovernanceState): string {
  return GOV_STATE_META[state].border
}

export function mapStateToMotion(state: GovernanceState): string {
  return GOV_STATE_META[state].motion
}
