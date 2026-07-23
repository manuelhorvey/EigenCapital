import { keepPreviousData } from '@tanstack/react-query'
import { createApiQuery } from '../lib/api'
import { z } from 'zod'

const AttributionLayerSchema = z.object({
  alpha_r: z.number().nullable(),
  alpha_status: z.enum(['APPLIED', 'NOT_TRIGGERED', 'NOT_AVAILABLE']),
})

const LatestAttributionSchema = z.object({
  trade_id: z.string(),
  decision_id: z.string().nullable(),
  lifecycle_version: z.string(),
  attribution_version: z.string(),
  realized_r: z.number(),
  holding_period_candles: z.number(),
  entry_archetype: z.string(),
  exit_reason: z.string(),
  asset: z.string(),
  created_at: z.string(),
  entry_alpha_r: z.number().nullable(),
  entry_alpha_status: z.enum(['APPLIED', 'NOT_TRIGGERED', 'NOT_AVAILABLE']),
  calibration_alpha_r: z.number().nullable(),
  calibration_alpha_status: z.enum(['APPLIED', 'NOT_TRIGGERED', 'NOT_AVAILABLE']),
  exit_alpha_r: z.number().nullable(),
  exit_alpha_status: z.enum(['APPLIED', 'NOT_TRIGGERED', 'NOT_AVAILABLE']),
  profit_floor_alpha_r: z.number().nullable(),
  profit_floor_alpha_status: z.enum(['APPLIED', 'NOT_TRIGGERED', 'NOT_AVAILABLE']),
  portfolio_alpha_r: z.number().nullable(),
  portfolio_alpha_status: z.enum(['APPLIED', 'NOT_TRIGGERED', 'NOT_AVAILABLE']),
  risk_alpha_r: z.number().nullable(),
  risk_alpha_status: z.enum(['APPLIED', 'NOT_TRIGGERED', 'NOT_AVAILABLE']),
  static_exit_r: z.number().nullable(),
  static_exit_version: z.string().nullable(),
  uncalibrated_signal_r: z.number().nullable(),
  uncalibrated_signal_version: z.string().nullable(),
  no_profit_floor_r: z.number().nullable(),
  no_profit_floor_version: z.string().nullable(),
})

export type LatestAttributionRecord = z.infer<typeof LatestAttributionSchema>

const useLatestAttributionQuery = createApiQuery<z.infer<typeof LatestAttributionSchema>>(
  '/attribution/latest.json',
  LatestAttributionSchema,
)

/** Fetches the most-recent closed-trade attribution record.
 *
 * The endpoint returns either a populated `LatestAttributionRecord` (after a
 * trade has closed) or may produce a schema mismatch when the file doesn't
 * exist yet — a 404 returns `{"error": "no_attribution"}` which fails
 * validation. The hook surfaces that as a typed query error.
 */
export function useLatestAttribution() {
  return useLatestAttributionQuery({ refetchInterval: 60_000, staleTime: 50_000, placeholderData: keepPreviousData })
}
