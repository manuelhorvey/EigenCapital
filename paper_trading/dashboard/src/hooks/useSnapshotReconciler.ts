import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { QUERY_KEYS } from '../lib/queryKeys'
import type { SystemBundle } from '../types/bundle'

/**
 * Detects engine restarts (sequence_id drops) and invalidates the
 * systemSnapshot cache when a stale snapshot would otherwise persist.
 *
 * Guards against:
 *  - Partial UI updates during mid-cycle snapshot regeneration
 *  - Stale selector reads after engine restart
 *  - Cross-cycle state bleed (old snapshot showing on new engine)
 */
export function useSnapshotReconciler(bundle: SystemBundle | undefined) {
  const queryClient = useQueryClient()
  const lastSeqId = useRef<number | null>(null)

  useEffect(() => {
    const seqId = bundle?.meta?.snapshot_sequence_id ?? null
    if (seqId === null) return

    // First mount — just record the baseline
    if (lastSeqId.current === null) {
      lastSeqId.current = seqId
      return
    }

    // Same sequence — nothing to reconcile
    if (seqId === lastSeqId.current) return

    const wasReset = seqId < lastSeqId.current
    const jumped = seqId - lastSeqId.current > 3

    // Engine restart (sequence_id dropped) or suspicious jump
    if (wasReset || jumped) {
      queryClient.setQueryData(QUERY_KEYS.system, bundle)
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.system })
    }

    lastSeqId.current = seqId
  }, [bundle?.meta?.snapshot_sequence_id, bundle, queryClient])
}
