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
  soft_warnings: z.array(z.string()),
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

export const WeeklyReviewSummarySchema = z.object({
  n_trades: z.number(),
  total_pnl: z.number(),
  total_return_pct: z.number(),
  win_rate: z.number(),
  tp_rate: z.number(),
  sl_rate: z.number(),
  signal_flip_rate: z.number(),
  profit_factor: z.number().nullable(),
  avg_r: z.number(),
  best_r_multiple: z.number(),
  worst_r_multiple: z.number(),
})

export const WeeklyReviewByAssetSchema = z.object({
  asset: z.string(),
  n_trades: z.number(),
  win_rate: z.number(),
  tp_rate: z.number(),
  sl_rate: z.number(),
  avg_r: z.number(),
  profit_factor: z.number().nullable(),
  pnl: z.number(),
})

export const WeeklyReviewExitBreakdownSchema = z.object({
  tp: z.number(),
  sl: z.number(),
  signal_flip: z.number(),
  other: z.number(),
})

export const WeeklyReviewStopOutSchema = z.object({
  stop_out_cooldowns_triggered: z.number(),
  estimated_churn_prevented: z.number(),
  assets_in_cooldown: z.array(z.string()),
})

export const WeeklyReviewGovernanceSchema = z.object({
  halted_assets: z.array(z.string()),
  most_common_validity: z.string(),
})

export const WeeklyReviewRegimeCorrelationSchema = z.object({
  regime: z.string(),
  n_trades: z.number(),
  win_rate: z.number(),
  sl_rate: z.number(),
})

export const WeeklyReviewVsPriorSchema = z.object({
  pnl_change: z.number(),
  win_rate_change: z.number(),
  sl_rate_change: z.number(),
  tp_rate_change: z.number(),
})

export const WeeklyReviewSchema = z.object({
  week_label: z.string(),
  generated_at: z.string(),
  summary: WeeklyReviewSummarySchema,
  by_asset: z.array(WeeklyReviewByAssetSchema),
  top_winners: z.array(z.record(z.string(), z.unknown())),
  top_losers: z.array(z.record(z.string(), z.unknown())),
  exit_reason_breakdown: WeeklyReviewExitBreakdownSchema,
  stop_out_cooldowns: WeeklyReviewStopOutSchema,
  governance_summary: WeeklyReviewGovernanceSchema,
  regime_correlation: z.array(WeeklyReviewRegimeCorrelationSchema),
  vs_prior_week: WeeklyReviewVsPriorSchema.nullable(),
})

export const HealthResponseSchema = z.object({
  assets: z.record(z.string(), AssetHealthSchema),
  system_health: SystemHealthSchema,
})

export const PortfolioSummarySchema = z.object({
  total_value: z.number(),
  mtm_value: z.number().optional(),
  total_return: z.number(),
  realized_value: z.number().optional(),
  realized_return: z.number().optional(),
  unrealized_pnl: z.number().optional(),
  days_running: z.number().optional(),
  runtime_hours: z.number().optional(),
  start_date: z.string().optional(),
  start_datetime: z.string().optional(),
  last_update: z.string().nullable().optional(),
  capital: z.number(),
  allocations: z.record(z.string(), z.number()).optional().default({}),
  deployment_cleared: z.boolean().optional(),
  open_positions: z.number().optional().default(0),
  closed_trades: z.number().optional().default(0),
  execution_state: z.string().optional(),
  average_validity_exposure: z.number().optional(),
  portfolio_drawdown: z.number().optional(),
  portfolio_peak_value: z.number().nullable().optional(),
}).passthrough()

export const EngineStatusSchema = z.object({
  initialized: z.boolean().optional().default(false),
  last_update: z.string().optional().default(''),
  start_time: z.string().optional().default(''),
  market_closed: z.boolean().optional(),
}).passthrough()

export const HaltConditionsSchema = z.object({
  drawdown: z.number().optional().default(0),
  monthly_pf: z.number().optional().default(0),
  signal_drought: z.number().optional().default(0),
  prob_drift: z.number().optional().default(0),
}).passthrough()

export const EngineSnapshotSchema = z.object({
  schema_version: z.string().optional().default('unknown'),
  timestamp: z.string(),
  portfolio: PortfolioSummarySchema,
  assets: z.record(z.string(), z.unknown()),
  open_positions: z.record(z.string(), z.unknown()).optional(),
  engine_status: EngineStatusSchema,
  halt_conditions: HaltConditionsSchema.optional().default({
    drawdown: 0,
    monthly_pf: 0,
    signal_drought: 0,
    prob_drift: 0,
  }),
  risk_signals: z.record(z.string(), z.unknown()).optional(),
  shadow_actions: z.record(z.string(), z.unknown()).optional(),
}).passthrough()
