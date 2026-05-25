import type { GovernanceState } from './governance'
import { governanceBadge } from './governance'

interface StatusBadgeProps {
  state: GovernanceState
  pulse?: boolean
  className?: string
}

export default function StatusBadge({ state, pulse = false, className = '' }: StatusBadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-semibold tracking-wide uppercase ${governanceBadge[state]} ${className}`}
    >
      {pulse && state === 'RED' && (
        <span className="w-1.5 h-1.5 rounded-full bg-gov-red state-pulse-red" />
      )}
      {pulse && state === 'GREEN' && (
        <span className="w-1.5 h-1.5 rounded-full bg-gov-green state-pulse-green" />
      )}
      {state}
    </span>
  )
}
