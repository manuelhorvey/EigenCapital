/** Calibration / governance state — use everywhere for consistent color psychology */

export type GovernanceState = 'LONG' | 'WARN' | 'SHORT' | 'INIT' | 'GRAY'

export const SIGNAL_STATES: GovernanceState[] = ['LONG', 'WARN', 'SHORT', 'INIT', 'GRAY']

export const signalBadge: Record<GovernanceState, string> = {
  LONG: 'bg-signal-long-muted text-signal-long border-signal-long/25',
  WARN: 'bg-signal-warn-muted text-signal-warn border-signal-warn/25',
  SHORT: 'bg-signal-short-muted text-signal-short border-signal-short/25',
  INIT: 'bg-signal-init-muted text-signal-init border-signal-init/25',
  GRAY: 'bg-signal-gray-muted text-signal-gray border-signal-gray/25',
}

export const signalDot: Record<GovernanceState, string> = {
  LONG: 'bg-signal-long',
  WARN: 'bg-signal-warn',
  SHORT: 'bg-signal-short',
  INIT: 'bg-signal-init',
  GRAY: 'bg-signal-gray',
}

export const signalText: Record<GovernanceState, string> = {
  LONG: 'text-signal-long',
  WARN: 'text-signal-warn',
  SHORT: 'text-signal-short',
  INIT: 'text-signal-init',
  GRAY: 'text-signal-gray',
}

export const signalBorder: Record<GovernanceState, string> = {
  LONG: 'border-l-signal-long',
  WARN: 'border-l-signal-warn',
  SHORT: 'border-l-signal-short',
  INIT: 'border-l-signal-init',
  GRAY: 'border-l-signal-gray',
}

export const signalBgMuted: Record<GovernanceState, string> = {
  LONG: 'bg-signal-long-muted2',
  WARN: 'bg-signal-warn-muted2',
  SHORT: 'bg-signal-short-muted2',
  INIT: 'bg-signal-init-muted2',
  GRAY: 'bg-signal-gray-muted2',
}

export function prematureRateState(rate: number | null): GovernanceState {
  if (rate === null) return 'INIT'
  if (rate > 0.3) return 'SHORT'
  if (rate > 0.1) return 'WARN'
  return 'LONG'
}

export function scalarToState(value: number): GovernanceState {
  if (value >= 1.0) return 'LONG'
  if (value > 0.7) return 'WARN'
  return 'SHORT'
}

export function regimeToState(regime: string): GovernanceState {
  if (regime === 'STRESSED') return 'SHORT'
  if (regime === 'THIN') return 'WARN'
  return 'LONG'
}

export function narrRegimeToState(regime: string | null): GovernanceState | null {
  if (!regime) return null
  if (regime === 'risk_off') return 'SHORT'
  if (regime === 'geopol_tension') return 'WARN'
  if (regime === 'risk_on') return 'LONG'
  return null
}

export function validityToState(state: string): GovernanceState {
  const s = state.toLowerCase()
  if (s === 'green') return 'LONG'
  if (s === 'yellow' || s === 'amber') return 'WARN'
  if (s === 'red') return 'SHORT'
  return 'INIT'
}

export function scoreToState(score: number): GovernanceState {
  if (score >= 0.8) return 'LONG'
  if (score >= 0.5) return 'WARN'
  return 'SHORT'
}

export function confToState(confidence: number): GovernanceState {
  const pct = Math.min(100, Math.max(0, confidence <= 1 ? confidence * 100 : confidence))
  if (pct >= 60) return 'LONG'
  if (pct >= 45) return 'WARN'
  return 'SHORT'
}

export function rrToState(rr: number): GovernanceState {
  if (rr >= 2) return 'LONG'
  if (rr >= 1) return 'WARN'
  return 'SHORT'
}

export function ddToState(drawdown: number): GovernanceState {
  if (drawdown > -3) return 'LONG'
  if (drawdown > -5) return 'WARN'
  return 'SHORT'
}

export function healthColorToState(color: string): GovernanceState {
  if (color === 'green') return 'LONG'
  if (color === 'amber') return 'WARN'
  if (color === 'red') return 'SHORT'
  return 'INIT'
}

/* ── State meta system (PR1) ────────────────────────────── */

export interface GovStateMeta {
  fill: string
  border: string
  dot: string
  motion: string
}

export const SIGNAL_STATE_META: Record<GovernanceState, GovStateMeta> = {
  LONG:  { fill: 'bg-signal-long text-white',               border: 'border-signal-long/25 bg-signal-long-muted text-signal-long', dot: 'bg-signal-long',  motion: '' },
  WARN: { fill: 'bg-signal-warn text-white',              border: 'border-signal-warn/25 bg-signal-warn-muted text-signal-warn', dot: 'bg-signal-warn', motion: 'animate-pulse-subtle' },
  SHORT:    { fill: 'bg-signal-short text-white',                 border: 'border-signal-short/25 bg-signal-short-muted text-signal-short',       dot: 'bg-signal-short',    motion: 'state-pulse-red' },
  INIT:   { fill: 'bg-signal-init text-white',                border: 'border-signal-init/25 bg-signal-init-muted text-signal-init',    dot: 'bg-signal-init',   motion: '' },
  GRAY:   { fill: 'bg-signal-gray text-white',                border: 'border-signal-gray/25 bg-signal-gray-muted text-signal-gray',    dot: 'bg-signal-gray',   motion: '' },
}

export function getSignalMeta(state: GovernanceState): GovStateMeta {
  return SIGNAL_STATE_META[state]
}

export function mapSignalToFill(state: GovernanceState): string {
  return SIGNAL_STATE_META[state].fill
}

export function mapSignalToBorder(state: GovernanceState): string {
  return SIGNAL_STATE_META[state].border
}

export function mapSignalToMotion(state: GovernanceState): string {
  return SIGNAL_STATE_META[state].motion
}
