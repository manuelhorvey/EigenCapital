import { useQuery } from '@tanstack/react-query'
import type { SlippageDistribution } from '../types/execution'

async function fetchSlippage(): Promise<SlippageDistribution> {
  const res = await fetch('/execution/slippage.json')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export function useExecutionSlippage() {
  return useQuery({
    queryKey: ['executionSlippage'],
    queryFn: fetchSlippage,
    refetchInterval: 60_000,
    staleTime: 50_000,
  })
}
