import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { fetchApi } from '../lib/api'
import { QUERY_KEYS } from '../lib/queryKeys'
import { EngineSnapshotSchema } from '../lib/schemas'
import type { SystemBundle } from '../types/bundle'

export function useSystemSnapshot<T = SystemBundle>(
  select?: (data: SystemBundle) => T
) {
  return useQuery({
    queryKey: QUERY_KEYS.system,
    queryFn: async () => {
      const json = await fetchApi<SystemBundle>('/state-bundle.json')
      const parsed = EngineSnapshotSchema.safeParse(json.snapshot)
      if (parsed.success) {
        json.snapshot = parsed.data as typeof json.snapshot
      } else {
        console.warn('[SNAPSHOT] Zod validation failed:', parsed.error.issues)
      }
      return json
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
