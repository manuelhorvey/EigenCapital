import { useQuery } from '@tanstack/react-query'
import { LiquidityDataSchema } from '../lib/schemas'
import type { z } from 'zod'

export type LiquidityData = z.infer<typeof LiquidityDataSchema>
export type LiquidityStatus = LiquidityData[string]

async function fetchLiquidity(): Promise<LiquidityData> {
  const resp = await fetch('/liquidity.json')
  if (!resp.ok) throw new Error('Failed to fetch liquidity')
  const json = await resp.json()
  const parsed = LiquidityDataSchema.safeParse(json)
  if (!parsed.success) {
    console.error('[Liquidity] validation failed:', parsed.error.issues)
    throw new Error('Invalid liquidity data from server')
  }
  return parsed.data
}

export function useLiquidity() {
  return useQuery<LiquidityData>({
    queryKey: ['liquidity'],
    queryFn: fetchLiquidity,
    refetchInterval: 60_000,
    staleTime: 60_000,
    gcTime: 300_000,
  })
}
