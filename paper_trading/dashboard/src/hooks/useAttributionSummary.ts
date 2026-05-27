import { useQuery } from '@tanstack/react-query'
import type { AttributionSummary } from '../types/attribution'

async function fetchAttributionSummary(): Promise<AttributionSummary> {
  const res = await fetch('/attribution/summary.json')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export function useAttributionSummary() {
  return useQuery({
    queryKey: ['attributionSummary'],
    queryFn: fetchAttributionSummary,
    refetchInterval: 60_000,
    staleTime: 50_000,
  })
}
