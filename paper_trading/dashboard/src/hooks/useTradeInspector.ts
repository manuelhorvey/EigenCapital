import { useMemo } from 'react'
import { useAttributionTrades } from './useAttributionTrades'
import type { TradeAttributionRecord } from './useAttributionTrades'

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

/** Finds a matching attribution trade by asset and optional dates, returning combined basic + attribution data. @returns {TradeInspectorData | null} - Matched trade data or null */
export function useTradeInspector(
  asset?: string,
  entryDate?: string,
  exitDate?: string,
): TradeInspectorData | null {
  const { data: allTrades } = useAttributionTrades(500)

  return useMemo(() => {
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
}
