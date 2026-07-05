import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { fetchApi } from '../lib/api'
import { QUERY_KEYS } from '../lib/queryKeys'
import { SystemBundleSchema } from '../lib/schemas'
import type { SystemBundle } from '../types/bundle'

let _lastContractVersion: number | null = null

export function useSystemSnapshot<T = SystemBundle>(
  select?: (data: SystemBundle) => T
) {
  return useQuery({
    queryKey: QUERY_KEYS.system,
    queryFn: async () => {
      const json = await fetchApi<unknown>('/state-bundle.json')
      const bundle = SystemBundleSchema.parse(json)
      const cv = bundle.snapshot.contract_version
      if (_lastContractVersion !== null && _lastContractVersion !== cv) {
        console.warn(`[SNAPSHOT] Contract version mismatch: was ${_lastContractVersion}, now ${cv}. Dashboard may be incompatible with engine.`)
      }
      _lastContractVersion = cv
      return bundle as unknown as SystemBundle
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
