import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../lib/api'

export interface FeatureImportance {
  feature?: string
  importance?: number
  type?: string
  error?: string
}

export interface TradeEntry {
  side: string
  entry: number
  exit: number
  return: number
  reason: string
  entry_date: string
  exit_date: string
  mae: number | null
  mfe: number | null
}

export interface DeepDiveData {
  asset: string
  feature_importance: FeatureImportance[]
  trades: TradeEntry[]
  final_signal: string | null
  sell_only: boolean
  tripwire_active: boolean
  last_signal: Record<string, unknown> | null
  metrics: Record<string, unknown> | null
}

export function useAssetDeepDive(name: string) {
  return useQuery({
    queryKey: ['assetDeepDive', name],
    queryFn: () => fetchApi<DeepDiveData>(`/asset/${name}.json`),
    enabled: !!name,
    staleTime: 60_000,
  })
}
