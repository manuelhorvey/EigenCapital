import { z } from 'zod'

export const GovernanceStateSchema = z.object({
  regime_sl_mult: z.number(),
  regime_size_scalar: z.number(),
  narrative_sl_mult: z.number(),
  narrative_size_scalar: z.number(),
  liquidity_sl_mult: z.number(),
  liquidity_size_scalar: z.number(),
  combined_sl_mult: z.number(),
  combined_size_scalar: z.number(),
  floor_active: z.boolean(),
  validity_state: z.string(),
  narrative_regime: z.string().nullable(),
  narrative_stale: z.boolean(),
  liquidity_regime: z.string(),
  halted: z.boolean(),
})

export const GovernanceDataSchema = z.record(z.string(), GovernanceStateSchema)

export const PSIFeatureEntrySchema = z.object({
  feature: z.string(),
  psi: z.number(),
  classification: z.string(),
  trend: z.string(),
  importance_score: z.number(),
})

export const PSIAssetStatusSchema = z.object({
  per_feature: z.array(PSIFeatureEntrySchema),
  worst_classification: z.string(),
  moderate_count: z.number(),
  severe_count: z.number(),
  psi_ok: z.boolean(),
  penalty: z.number(),
})

export const PSIDataSchema = z.record(z.string(), PSIAssetStatusSchema)

export const LiquidityStatusSchema = z.object({
  regime: z.string(),
  sl_mult: z.number(),
  size_scalar: z.number(),
})

export const LiquidityDataSchema = z.record(z.string(), LiquidityStatusSchema)

export const NarrativeActiveSchema = z.object({
  overall_regime: z.string().optional(),
  current_narrative: z.string().optional(),
  current_rationale: z.string().optional(),
}).passthrough()

export const NarrativeStatusSchema = z.object({
  week_start: z.string(),
  active: NarrativeActiveSchema.nullable(),
  pending: z.record(z.string(), z.unknown()).nullable(),
  stale: z.boolean(),
  fetch_error: z.record(z.string(), z.unknown()).nullable(),
  has_pending: z.boolean(),
  needs_confirmation: z.boolean(),
})

export const RiskParityDataSchema = z.object({
  weights: z.record(z.string(), z.number()).optional().default({}),
  capital_allocations: z.record(z.string(), z.number()).optional().default({}),
  total_value: z.number().optional().default(0),
})

export const TradeEntrySchema = z.object({
  asset: z.string(),
  side: z.string(),
  entry: z.number(),
  exit: z.number(),
  return: z.number(),
  reason: z.string(),
  entry_date: z.string(),
  exit_date: z.string(),
  bars: z.number().optional(),
})

export const EquityHistoryPointSchema = z.object({
  timestamp: z.string(),
  portfolio_value: z.number(),
  portfolio_return: z.number(),
  drawdown: z.number(),
  gross_exposure: z.number(),
  net_exposure: z.number(),
  assets: z.record(z.string(), z.number()),
})

export const HealthComponentSchema = z.object({
  validity: z.number(),
  drift: z.number(),
  pnl_stability: z.number(),
  shadow_agreement: z.number(),
  stress_robustness: z.number(),
})

export const AssetHealthSchema = z.object({
  asset: z.string(),
  health_score: z.number(),
  health_label: z.string(),
  health_color: z.string(),
  components: HealthComponentSchema,
  limiting_factors: z.array(z.object({ component: z.string(), score: z.number() })),
  validity_state: z.string(),
})

export const SystemHealthSchema = z.object({
  mean_health_score: z.number(),
  n_assets: z.number(),
  healthiest_asset: z.string().nullable(),
  weakest_asset: z.string().nullable(),
  n_healthy: z.number(),
  n_degraded: z.number(),
  n_critical: z.number(),
})

export const HealthResponseSchema = z.object({
  assets: z.record(z.string(), AssetHealthSchema),
  system_health: SystemHealthSchema,
})
