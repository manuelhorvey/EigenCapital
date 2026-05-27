import { useQuery } from '@tanstack/react-query'
import type { ExecutionQualityResponse } from '../types/execution'

async function fetchExecutionQuality(): Promise<ExecutionQualityResponse> {
  const res = await fetch('/execution/quality.json')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export function useExecutionQuality() {
  return useQuery({
    queryKey: ['executionQuality'],
    queryFn: fetchExecutionQuality,
    refetchInterval: 60_000,
    staleTime: 50_000,
  })
}
