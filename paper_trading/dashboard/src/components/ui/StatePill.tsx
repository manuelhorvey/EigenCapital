import type { GovernanceState } from './governance'
import { governanceDot, governanceText } from './governance'

interface StatePillProps {
  state: GovernanceState
  pulse?: boolean
  className?: string
}

export default function StatePill({ state, pulse = false, className = '' }: StatePillProps) {
  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`}>
      <span
        className={`w-2 h-2 rounded-full ${governanceDot[state]} ${pulse ? (state === 'RED' ? 'state-pulse-red' : state === 'GREEN' ? 'state-pulse-green' : '') : ''}`}
      />
      <span className={`text-[11px] font-semibold ${governanceText[state]}`}>{state}</span>
    </span>
  )
}
