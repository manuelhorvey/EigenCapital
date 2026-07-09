import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { fetchApi } from '../lib/api'
import { addErrorBreadcrumb } from '../lib/errorReporting'
import { WalResponseSchema } from '../lib/schemas'
import type { z } from 'zod'

export type WalEvent = z.infer<typeof WalResponseSchema>['events'][number]

/** Fetches WAL (Write-Ahead Log) event timeline for a given asset. @returns {object} - React Query result with WalResponse containing events */
export function useWalTimeline(assetName: string) {
  return useQuery({
    queryKey: ['walTimeline', assetName],
    queryFn: async () => {
      const json = await fetchApi<unknown>(`/wal/${assetName}.json`)
      const parsed = WalResponseSchema.safeParse(json)
      if (!parsed.success) {
        console.error('[WAL] validation failed:', parsed.error.issues)
        addErrorBreadcrumb('WAL', `Validation failed for ${assetName}`)
        return { events: [], total: 0, asset: assetName }
      }
      return parsed.data
    },
    refetchInterval: 30_000,
    placeholderData: keepPreviousData,
    staleTime: 10_000,
    enabled: !!assetName,
  })
}

export function groupWalEvents(events: WalEvent[]) {
  const groups: { featureHash: string; ts: string; seq: number; events: WalEvent[] }[] = []
  const map = new Map<string, WalEvent[]>()

  for (const ev of events) {
    const fh = ev.payload?.feature_hash as string | undefined
    if (!fh) continue
    const list = map.get(fh) ?? []
    list.push(ev)
    map.set(fh, list)
  }

  for (const [fh, list] of map) {
    const sorted = list.sort((a, b) => a.sequence - b.sequence)
    groups.push({
      featureHash: fh,
      ts: sorted[0].timestamp ?? '',
      seq: sorted[0].sequence,
      events: sorted,
    })
  }

  groups.sort((a, b) => b.seq - a.seq)
  return groups
}