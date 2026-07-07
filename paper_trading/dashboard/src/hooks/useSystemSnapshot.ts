import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { fetchApi } from '../lib/api'
import { QUERY_KEYS } from '../lib/queryKeys'
import { SystemBundleSchema } from '../lib/schemas'
import type { SystemBundle } from '../types/bundle'

let _lastContractVersion: number | null = null

/** Fetches the full system bundle snapshot with optional data selector. @returns {object} - React Query result containing the SystemBundle or selected subset */
export function useSystemSnapshot<T = SystemBundle>(
  select?: (data: SystemBundle) => T
) {
  return useQuery({
    queryKey: QUERY_KEYS.system,
    queryFn: async () => {
      const json = await fetchApi<unknown>('/state-bundle.json')
      const parsed = SystemBundleSchema.passthrough().safeParse(json)
      if (parsed.success) {
        const cv = parsed.data.snapshot.contract_version
        if (_lastContractVersion !== null && _lastContractVersion !== cv) {
          console.warn(`[SNAPSHOT] Contract version mismatch: was ${_lastContractVersion}, now ${cv}. Dashboard may be incompatible with engine.`)
        }
        _lastContractVersion = cv
        return parsed.data as unknown as SystemBundle
      }
      console.error('[SNAPSHOT] Bundle validation failed — schema drift detected:', parsed.error.issues)
      return json as unknown as SystemBundle
    },
    refetchInterval: (q) => {
      const closed = q.state.data?.snapshot?.engine_status?.market_closed
      return closed ? 30_000 : 5_000
    },
    staleTime: 3_000,
    placeholderData: keepPreviousData,
    select,
    retry: 2,
    retryDelay: 1_000,
  })
}
