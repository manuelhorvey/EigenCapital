import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { QUERY_KEYS } from '../lib/queryKeys'
import type { SystemBundle } from '../types/bundle'

/**
 * Detects engine restarts (sequence_id drops) and contract_version changes,
 * invalidating the systemSnapshot cache when stale data would otherwise persist.
 *
 * Guards against:
 *  - Partial UI updates during mid-cycle snapshot regeneration
 *  - Stale selector reads after engine restart
 *  - Cross-cycle state bleed (old snapshot showing on new engine)
 *  - Schema-incompatible snapshots after engine version change
 */
/** Detects engine restarts (sequence_id drops) and contract_version changes, invalidating cache to prevent stale cross-cycle state bleed. */
export function useSnapshotReconciler(bundle: SystemBundle | undefined) {
  const queryClient = useQueryClient()
  const lastSeqId = useRef<number | null>(null)
  const lastContractVersion = useRef<number | null>(null)

  useEffect(() => {
    const seqId = bundle?.meta?.snapshot_sequence_id ?? null
    const contractVersion = bundle?.snapshot?.contract_version ?? null
    if (seqId === null) return

    // First mount — just record the baseline
    if (lastSeqId.current === null) {
      lastSeqId.current = seqId
      lastContractVersion.current = contractVersion
      return
    }

    // Contract version changed — engine was rebuilt with new schema
    if (contractVersion !== null && lastContractVersion.current !== null &&
        contractVersion !== lastContractVersion.current) {
      queryClient.setQueryData(QUERY_KEYS.system, bundle)
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.system })
      lastContractVersion.current = contractVersion
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
  }, [bundle?.meta?.snapshot_sequence_id, bundle?.snapshot?.contract_version, bundle, queryClient])
}
