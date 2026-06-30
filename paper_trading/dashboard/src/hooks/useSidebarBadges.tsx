import { useMemo } from 'react'
import { useSystemSnapshot } from './useSystemSnapshot'
import { systemSelectors } from '../selectors/system'

export interface SidebarBadges {
  trading?: number
  risk?: number
}

export function useSidebarBadges(): SidebarBadges {
  const { data: snapshot } = useSystemSnapshot(systemSelectors.snapshot)

  return useMemo(() => {
    const result: SidebarBadges = {}

    if (snapshot?.emergency_halt) {
      result.risk = 1
    }

    const admission = snapshot?.portfolio?.admission
    if (admission && admission.n_rejected > 0) {
      result.trading = admission.n_rejected
    }

    return result
  }, [snapshot])
}
