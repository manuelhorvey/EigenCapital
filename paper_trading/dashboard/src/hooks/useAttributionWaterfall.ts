import { useQuery } from '@tanstack/react-query'
import type { AttributionWaterfall } from '../types/attribution'

async function fetchWaterfall(): Promise<AttributionWaterfall> {
  const res = await fetch('/attribution/waterfall.json')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export function useAttributionWaterfall() {
  return useQuery({
    queryKey: ['attributionWaterfall'],
    queryFn: fetchWaterfall,
    refetchInterval: 60_000,
    staleTime: 50_000,
  })
}
