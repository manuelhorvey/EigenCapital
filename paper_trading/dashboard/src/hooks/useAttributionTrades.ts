import { useQuery } from '@tanstack/react-query'
import { z } from 'zod'
import { fetchApi } from '../lib/api'
import { addErrorBreadcrumb } from '../lib/errorReporting'
import type { TradeAttributionRecord } from '../types/attribution'

// ── Zod schema for attribution trades ────────────────────────────────────
// Mirrors the SQLite attribution table columns. Fields not in the DB
// (friction sub-domains, decision quality, etc.) get catch-all defaults
// so no malformed data reaches UI components.

function coerceBool(v: unknown): boolean | null {
  if (v === true || v === 1) return true
  if (v === false || v === 0) return false
  return null
}

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
  pred_forecast_direction_correct: z.union([z.boolean(), z.null()]).catch(null),
  pred_archetype_at_entry: z.string(),
  pred_regime_at_entry: z.string(),
  exec_entry_type: z.string(),
  exec_entry_slippage_bps: z.number(),
  exec_deferred_bars: z.number(),
  exec_entry_timing_efficiency: z.union([z.number(), z.null()]).catch(null),
  exec_counterfactual_entry_timing_r: z.union([z.number(), z.null()]).catch(null),
  exit_exit_reason: z.union([z.string(), z.null()]).catch(""),
  exit_realized_r: z.number().catch(0),
  exit_theoretical_r: z.union([z.number(), z.null()]).catch(null),
  exit_mae: z.number().catch(0),
  exit_mfe: z.number().catch(0),
  exit_mae_per_bar: z.number().catch(0),
  exit_mfe_per_bar: z.number().catch(0),
  exit_bars_held: z.number().catch(0),
  exit_archetype: z.union([z.string(), z.null()]).catch(""),
  friction_entry_slippage_bps: z.number().catch(0),
  friction_exit_slippage_bps: z.number().catch(0),
  friction_gap_fill: z.union([z.boolean(), z.null()]).catch(null),
  friction_partial_fill: z.union([z.boolean(), z.null()]).catch(null),
  friction_fill_qty_ratio: z.number().catch(1),
  friction_latency_bars: z.number().catch(0),
  friction_counterfactual_ideal_fill_r: z.union([z.number(), z.null()]).catch(null),
  friction_counterfactual_real_fill_r: z.union([z.number(), z.null()]).catch(null),
  dq_entry_pressure_pct: z.union([z.number(), z.null()]).catch(null),
  dq_spread_rank: z.union([z.number(), z.null()]).catch(null),
  dq_volatility_rank: z.union([z.number(), z.null()]).catch(null),
  dq_liquidity_rank: z.union([z.number(), z.null()]).catch(null),
}).transform((row) => ({
  ...row,
  pred_forecast_direction_correct: coerceBool(row.pred_forecast_direction_correct),
  friction_gap_fill: coerceBool(row.friction_gap_fill),
  friction_partial_fill: coerceBool(row.friction_partial_fill),
}))

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
    addErrorBreadcrumb('AttributionTrades', 'Validation failed')
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
