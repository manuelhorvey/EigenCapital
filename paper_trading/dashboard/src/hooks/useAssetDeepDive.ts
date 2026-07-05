import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../lib/api'
import { DeepDiveDataSchema } from '../lib/schemas'
import type { z } from 'zod'

export type DeepDiveData = z.infer<typeof DeepDiveDataSchema>
export type TradeEntry = DeepDiveData['trades'][number]
export type FeatureImportance = DeepDiveData['feature_importance'][number]

export function useAssetDeepDive(name: string) {
  return useQuery({
    queryKey: ['assetDeepDive', name],
    queryFn: async () => {
      const json = await fetchApi<unknown>(`/asset/${name}.json`)
      return DeepDiveDataSchema.parse(json)
    },
    enabled: !!name,
    staleTime: 60_000,
  })
}
