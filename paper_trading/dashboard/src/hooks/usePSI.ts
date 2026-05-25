import { useQuery } from '@tanstack/react-query'
import { PSIDataSchema } from '../lib/schemas'
import type { z } from 'zod'

export type PSIFeatureEntry = z.infer<typeof PSIDataSchema>[string]['per_feature'][number]
export type PSIAssetStatus = z.infer<typeof PSIDataSchema>[string]
export type PSIData = z.infer<typeof PSIDataSchema>

async function fetchPSI(): Promise<PSIData> {
  const resp = await fetch('/psi.json')
  if (!resp.ok) throw new Error('Failed to fetch PSI drift')
  const json = await resp.json()
  const parsed = PSIDataSchema.safeParse(json)
  if (!parsed.success) {
    console.error('[PSI] validation failed:', parsed.error.issues)
    throw new Error('Invalid PSI drift data from server')
  }
  return parsed.data
}

export function usePSI() {
  return useQuery<PSIData>({
    queryKey: ['psi'],
    queryFn: fetchPSI,
    refetchInterval: 60_000,
    staleTime: 60_000,
    gcTime: 300_000,
  })
}
