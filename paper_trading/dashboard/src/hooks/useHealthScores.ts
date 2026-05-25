import { useQuery } from '@tanstack/react-query'
import { HealthResponseSchema } from '../lib/schemas'
import { useMarketClosed } from './useMarketClosed'
import type { z } from 'zod'

export type HealthComponent = z.infer<typeof HealthResponseSchema>['assets'][string]['components']
export type AssetHealth = z.infer<typeof HealthResponseSchema>['assets'][string]
export type SystemHealth = z.infer<typeof HealthResponseSchema>['system_health']
export type HealthResponse = z.infer<typeof HealthResponseSchema>

async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch('/health.json')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  const parsed = HealthResponseSchema.safeParse(json)
  if (!parsed.success) {
    console.error('[Health] validation failed:', parsed.error.issues)
    throw new Error('Invalid health data from server')
  }
  return parsed.data
}

export function useHealthScores() {
  const closed = useMarketClosed()
  return useQuery({
    queryKey: ['healthScores'],
    queryFn: fetchHealth,
    refetchInterval: closed ? 300_000 : 60_000,
    staleTime: closed ? 290_000 : 50_000,
  })
}
