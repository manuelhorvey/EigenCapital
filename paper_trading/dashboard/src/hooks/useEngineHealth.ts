import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../lib/api'
import { QUERY_KEYS } from '../lib/queryKeys'
import { addErrorBreadcrumb } from '../lib/errorReporting'
import { EngineHealthSchema } from '../lib/schemas'
import type { z } from 'zod'

export type EngineHealth = z.infer<typeof EngineHealthSchema>

const FALLBACK: EngineHealth = {
  status: 'no_state',
  server_time: new Date().toISOString(),
  state_exists: false,
  state_file_age_s: -1,
  state_sequence_id: null,
  engine_alive: false,
}

/** Polls the engine health endpoint at low frequency (30s).
 *  Primary health data comes via useSystemSnapshot (bundle).
 *  This is a lightweight fallback for engine_alive detection. */
export function useEngineHealth() {
  return useQuery({
    queryKey: QUERY_KEYS.engine,
    queryFn: async () => {
      const json = await fetchApi<unknown>('/health')
      const parsed = EngineHealthSchema.safeParse(json)
      if (!parsed.success) {
        console.error('[EngineHealth] validation failed:', parsed.error.issues)
        addErrorBreadcrumb('EngineHealth', 'Validation failed')
        return FALLBACK
      }
      return parsed.data
    },
    refetchInterval: 30_000,
    staleTime: 15_000,
    retry: 2,
    retryDelay: 1_000,
    placeholderData: (previousData: EngineHealth | undefined) => previousData ?? FALLBACK,
  })
}
