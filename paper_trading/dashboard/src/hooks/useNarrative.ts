import { useQuery, useQueryClient } from '@tanstack/react-query'
import { NarrativeStatusSchema } from '../lib/schemas'
import type { z } from 'zod'

export type NarrativeStatus = z.infer<typeof NarrativeStatusSchema>

async function fetchNarrative(): Promise<NarrativeStatus> {
  const resp = await fetch('/narrative.json')
  if (!resp.ok) throw new Error('Failed to fetch narrative')
  const json = await resp.json()
  const parsed = NarrativeStatusSchema.safeParse(json)
  if (!parsed.success) {
    console.error('[Narrative] validation failed:', parsed.error.issues)
    throw new Error('Invalid narrative data from server')
  }
  return parsed.data
}

export function useNarrative() {
  return useQuery<NarrativeStatus>({
    queryKey: ['narrative'],
    queryFn: fetchNarrative,
    refetchInterval: 300_000,
    staleTime: 300_000,
    gcTime: 600_000,
  })
}

export function useConfirmNarrative() {
  const queryClient = useQueryClient()
  return async () => {
    const resp = await fetch('/narrative/confirm', { method: 'POST' })
    if (!resp.ok) throw new Error('Failed to confirm narrative')
    await queryClient.invalidateQueries({ queryKey: ['narrative'] })
    await queryClient.invalidateQueries({ queryKey: ['governance'] })
    return resp.json()
  }
}
