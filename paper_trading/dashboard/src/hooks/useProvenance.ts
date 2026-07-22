import { createApiQuery } from '../lib/api'
import { ProvenanceResponseSchema } from '../lib/schemas'

const useProvenanceQuery = createApiQuery(
  '/provenance.json?limit=100',
  ProvenanceResponseSchema,
  'provenance',
)

export function useProvenance() {
  return useProvenanceQuery({ refetchInterval: 30_000, staleTime: 25_000 })
}
