import { useQuery } from '@tanstack/react-query'
import type { ShadowDivergenceSummary } from '../types/shadow'

async function fetchShadowSummary(): Promise<ShadowDivergenceSummary> {
  const res = await fetch('/shadow/summary.json')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export function useShadowSummary() {
  return useQuery({
    queryKey: ['shadowSummary'],
    queryFn: fetchShadowSummary,
    refetchInterval: 60_000,
    staleTime: 50_000,
  })
}
