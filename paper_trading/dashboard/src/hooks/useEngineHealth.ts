import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../lib/api'
import { QUERY_KEYS } from '../lib/queryKeys'
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

export function useEngineHealth() {
  return useQuery({
    queryKey: QUERY_KEYS.engine,
    queryFn: async () => {
      const json = await fetchApi<unknown>('/health')
      return EngineHealthSchema.parse(json)
    },
    refetchInterval: 5_000,
    staleTime: 0,
    retry: 2,
    retryDelay: 1_000,
    placeholderData: FALLBACK,
  })
}