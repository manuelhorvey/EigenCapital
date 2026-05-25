import { useQuery } from '@tanstack/react-query'
import { RiskParityDataSchema } from '../lib/schemas'
import type { z } from 'zod'

export type RiskParityData = z.infer<typeof RiskParityDataSchema>

async function fetchRiskParity(): Promise<RiskParityData> {
  const resp = await fetch('/risk-parity.json')
  if (!resp.ok) throw new Error('Failed to fetch risk parity')
  const json = await resp.json()
  const parsed = RiskParityDataSchema.safeParse(json)
  if (!parsed.success) {
    console.error('[RiskParity] validation failed:', parsed.error.issues)
    throw new Error('Invalid risk parity data from server')
  }
  return parsed.data
}

export function useRiskParity() {
  return useQuery<RiskParityData>({
    queryKey: ['riskParity'],
    queryFn: fetchRiskParity,
    refetchInterval: 30_000,
    staleTime: 15_000,
  })
}
