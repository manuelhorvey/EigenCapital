import { useMemo } from 'react'
import { useAttributionTrades } from './useAttributionTrades'
import type { TradeAttributionRecord } from '../types/attribution'

export interface TradeInspectorData {
  basic: {
    asset: string
    side: string
    entry_date: string
    exit_date: string
    entry_price: number
    exit_price: number
    realized_r: number
    realized_pnl: number
  }
  attribution: TradeAttributionRecord | null
}

export function useTradeInspector(
  asset?: string,
  entryDate?: string,
  exitDate?: string,
): { data: TradeInspectorData | null; isLoading: boolean } {
  const { data: allTrades, isPending, isFetching } = useAttributionTrades(
    200,
    0,
    asset ? { asset } : undefined,
  )

  const data = useMemo(() => {
    if (!asset || !allTrades) return null

    const match = allTrades.find(t =>
      t.asset === asset &&
      (!entryDate || t.entry_date === entryDate) &&
      (!exitDate || t.exit_date === exitDate),
    )

    if (!match) return null

    return {
      basic: {
        asset: match.asset,
        side: match.side,
        entry_date: match.entry_date,
        exit_date: match.exit_date,
        entry_price: match.entry_price,
        exit_price: match.exit_price,
        realized_r: match.exit_realized_r,
        realized_pnl: match.realized_pnl,
      },
      attribution: match,
    }
  }, [asset, entryDate, exitDate, allTrades])

  return { data, isLoading: isPending || isFetching }
}
