import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../lib/api'

export interface EngineHealth {
  status: 'ok' | 'stale' | 'no_state'
  server_time: string
  state_exists: boolean
  state_file_age_s: number
  state_sequence_id: number | null
  engine_alive: boolean
}

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
    queryKey: ['engineHealth'],
    queryFn: () => fetchApi<EngineHealth>('/health'),
    refetchInterval: 5_000,
    staleTime: 0,
    retry: 2,
    retryDelay: 1_000,
    placeholderData: FALLBACK,
  })
}