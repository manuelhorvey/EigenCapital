import type { GovernanceState } from './governance'
import { governanceBadge } from './governance'

interface StatusBadgeProps {
  state: GovernanceState
  className?: string
}

export default function StatusBadge({ state, className = '' }: StatusBadgeProps) {
  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded border text-[10px] font-semibold tracking-wide uppercase ${governanceBadge[state]} ${className}`}
    >
      {state}
    </span>
  )
}
