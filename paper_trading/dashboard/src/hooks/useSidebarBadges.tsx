import { useMemo } from 'react'
import { useSystemSnapshot } from './useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import { useEngineHealth } from './useEngineHealth'

export type EngineState = 'alive' | 'stale' | 'dead'

export interface SidebarBadges {
  trading?: number
  risk?: number
  /** Engine heartbeat state — null on initial fetch (loading). */
  engine?: EngineState
}

export function useSidebarBadges(): SidebarBadges {
  const { data: snapshot } = useSystemSnapshot(systemSelectors.snapshot)
  const health = useEngineHealth()

  return useMemo(() => {
    const result: SidebarBadges = {}

    if (snapshot?.emergency_halt) {
      result.risk = 1
    }

    const admission = snapshot?.portfolio?.admission
    if (admission && admission.n_rejected > 0) {
      result.trading = admission.n_rejected
    }

    // Engine heartbeat: error → dead, stale → stale, alive → alive.
    if (health.isError) {
      result.engine = 'dead'
    } else if (!health.isLoading && health.data) {
      result.engine = health.data.engine_alive ? 'alive' : 'stale'
    }

    return result
  }, [snapshot, health.isError, health.isLoading, health.data])
}
