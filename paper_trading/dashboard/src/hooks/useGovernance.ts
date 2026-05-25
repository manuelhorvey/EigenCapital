import { useQuery } from '@tanstack/react-query'
import { GovernanceDataSchema } from '../lib/schemas'
import type { z } from 'zod'

export type GovernanceState = z.infer<typeof GovernanceDataSchema>[string]
export type GovernanceData = z.infer<typeof GovernanceDataSchema>

async function fetchGovernance(): Promise<GovernanceData> {
  const resp = await fetch('/governance.json')
  if (!resp.ok) throw new Error('Failed to fetch governance')
  const json = await resp.json()
  const parsed = GovernanceDataSchema.safeParse(json)
  if (!parsed.success) {
    console.error('[Governance] validation failed:', parsed.error.issues)
    throw new Error('Invalid governance data from server')
  }
  return parsed.data
}

export function useGovernance() {
  return useQuery<GovernanceData>({
    queryKey: ['governance'],
    queryFn: fetchGovernance,
    refetchInterval: 30_000,
    staleTime: 25_000,
    gcTime: 300_000,
  })
}
