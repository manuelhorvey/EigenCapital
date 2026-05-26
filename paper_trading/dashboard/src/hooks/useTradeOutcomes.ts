import { useQuery } from '@tanstack/react-query'

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

async function fetchTradeOutcomes(): Promise<TradeOutcomesData> {
  const res = await fetch('/trade-outcomes.json')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  return json as TradeOutcomesData
}

export function useTradeOutcomes() {
  const { data, isPending, isError } = useQuery({
    queryKey: ['tradeOutcomes'],
    queryFn: fetchTradeOutcomes,
    refetchInterval: 30_000,
    staleTime: 25_000,
  })

  const outcomes = data ?? null

  return { outcomes, isPending, isError }
}
