import { createApiQuery } from '../lib/api'

export interface AssetOutcome {
  asset: string
  n_trades: number
  tp_rate: number
  sl_rate: number
  signal_flip_rate: number
  avg_r: number
  win_rate: number
  profit_factor: number | null
}

export interface TradeOutcomesData {
  overall: {
    tp_rate: number
    sl_rate: number
    signal_flip_rate: number
    avg_r: number
    win_rate: number
    profit_factor: number | null
  }
  by_asset: AssetOutcome[]
}

const useTradeOutcomesQuery = createApiQuery<TradeOutcomesData>('/trade-outcomes.json')

export function useTradeOutcomes() {
  const { data, isPending, isError, refetch } = useTradeOutcomesQuery({
    refetchInterval: 30_000,
    staleTime: 25_000,
  })
  return { outcomes: data ?? null, isPending, isError, refetch }
}
