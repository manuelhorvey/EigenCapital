/** Calibration / governance state — use everywhere for consistent color psychology */

export type GovernanceState = 'GREEN' | 'YELLOW' | 'RED' | 'INIT'

export const GOVERNANCE_STATES: GovernanceState[] = ['GREEN', 'YELLOW', 'RED', 'INIT']

export const governanceBadge: Record<GovernanceState, string> = {
  GREEN: 'bg-gov-green-muted text-gov-green border-gov-green/25',
  YELLOW: 'bg-gov-yellow-muted text-gov-yellow border-gov-yellow/25',
  RED: 'bg-gov-red-muted text-gov-red border-gov-red/25',
  INIT: 'bg-gov-init-muted text-gov-init border-gov-init/25',
}

export const governanceDot: Record<GovernanceState, string> = {
  GREEN: 'bg-gov-green',
  YELLOW: 'bg-gov-yellow',
  RED: 'bg-gov-red',
  INIT: 'bg-gov-init',
}

export const governanceText: Record<GovernanceState, string> = {
  GREEN: 'text-gov-green',
  YELLOW: 'text-gov-yellow',
  RED: 'text-gov-red',
  INIT: 'text-gov-init',
}

export function prematureRateState(rate: number | null): GovernanceState {
  if (rate === null) return 'INIT'
  if (rate > 0.3) return 'RED'
  if (rate > 0.1) return 'YELLOW'
  return 'GREEN'
}

export function healthColorToState(color: string): GovernanceState {
  if (color === 'green') return 'GREEN'
  if (color === 'amber') return 'YELLOW'
  if (color === 'red') return 'RED'
  return 'INIT'
}
