import { useQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { fetchApi } from '../lib/api'
import type { TradeAttributionRecord } from '../types/attribution'

// ── Zod schema for attribution trades ────────────────────────────────────
// Mirrors the TradeAttributionRecord interface to catch backend schema drift
// before malformed data reaches UI components (audit finding: missing validation).

const TradeAttributionRecordSchema = z.object({
  trade_id: z.string(),
  asset: z.string(),
  entry_date: z.string(),
  exit_date: z.string(),
  side: z.string(),
  entry_price: z.number(),
  exit_price: z.number(),
  realized_return: z.number(),
  realized_pnl: z.number(),
  pred_signal: z.string(),
  pred_confidence: z.number(),
  pred_forecast_direction_correct: z.boolean().nullable(),
  pred_archetype_at_entry: z.string(),
  pred_regime_at_entry: z.string(),
  exec_entry_type: z.string(),
  exec_entry_slippage_bps: z.number(),
  exec_deferred_bars: z.number(),
  exec_entry_timing_efficiency: z.number().nullable(),
  exec_counterfactual_entry_timing_r: z.number().nullable(),
  exit_exit_reason: z.string(),
  exit_realized_r: z.number(),
  exit_theoretical_r: z.number(),
  exit_mae: z.number(),
  exit_mfe: z.number(),
  exit_mae_per_bar: z.number(),
  exit_mfe_per_bar: z.number(),
  exit_bars_held: z.number(),
  exit_archetype: z.string(),
  friction_entry_slippage_bps: z.number(),
  friction_exit_slippage_bps: z.number(),
  friction_gap_fill: z.boolean(),
  friction_partial_fill: z.boolean(),
  friction_fill_qty_ratio: z.number(),
  friction_latency_bars: z.number(),
  friction_counterfactual_ideal_fill_r: z.number().nullable(),
  friction_counterfactual_real_fill_r: z.number().nullable(),
  dq_entry_pressure_pct: z.number().nullable(),
  dq_spread_rank: z.number().nullable(),
  dq_volatility_rank: z.number().nullable(),
  dq_liquidity_rank: z.number().nullable(),
})

async function fetchAttributionTrades(
  limit: number,
  offset: number,
  filters?: { archetype?: string; regime?: string; asset?: string },
): Promise<TradeAttributionRecord[]> {
  const qs = new URLSearchParams()
  qs.set('limit', String(limit))
  qs.set('offset', String(offset))
  if (filters?.archetype) qs.set('archetype', filters.archetype)
  if (filters?.regime) qs.set('regime', filters.regime)
  if (filters?.asset) qs.set('asset', filters.asset)
  const json = await fetchApi<unknown>(`/attribution/trades.json?${qs}`)
  const parsed = z.array(TradeAttributionRecordSchema).safeParse(json)
  if (!parsed.success) {
    console.error('[AttributionTrades] validation failed:', parsed.error.issues)
    throw new Error('Invalid attribution trade data from server')
  }
  return parsed.data as TradeAttributionRecord[]
}

/** Fetches paginated attribution trades with optional archetype/regime/asset filters. @returns {object} - React Query result with TradeAttributionRecord array */
export function useAttributionTrades(
  limit = 50,
  offset = 0,
  filters?: { archetype?: string; regime?: string; asset?: string },
) {
  return useQuery({
    queryKey: ['attributionTrades', limit, offset, filters],
    queryFn: () => fetchAttributionTrades(limit, offset, filters),
    refetchInterval: 60_000,
    staleTime: 50_000,
  })
}
