import { createApiQuery } from '../lib/api'
import { ProvenanceStatsSchema } from '../lib/schemas'

const useProvenanceStatsQuery = createApiQuery(
  '/provenance/stats.json',
  ProvenanceStatsSchema,
  'provenanceStats',
)

export function useProvenanceStats() {
  return useProvenanceStatsQuery({ refetchInterval: 30_000, staleTime: 25_000 })
}
