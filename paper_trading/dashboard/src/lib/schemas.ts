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
  SL: z.number(),
  TP: z.number(),
  BREAKEVEN: z.number(),
  FLIP: z.number(),
  EXPIRY: z.number(),
  MANUAL: z.number(),
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

// ── Position concentration ─────────────────────────────────────────

export const PositionConcentrationSchema = z.object({
  long: z.number(),
  short: z.number(),
  total: z.number(),
  skew: z.number(),
  dominant_side: z.string(),
  threshold: z.number(),
  alert: z.boolean(),
})

// ── Factor exposures ───────────────────────────────────────────────

export const FactorExposuresSchema = z.object({
  exposures: z.record(z.string(), z.number()),
  violations: z.record(z.string(), z.object({
    exposure: z.number(),
    limit_lo: z.number(),
    limit_hi: z.number(),
    violation: z.string().nullable(),
  })),
  n_violations: z.number(),
  within_limits: z.boolean(),
})

// ── Live Sharpe ────────────────────────────────────────────────────

export const LiveSharpeSchema = z.object({
  available: z.boolean(),
  reason: z.string().optional(),
  n_cycles: z.number().optional(),
  n_days: z.number().optional(),
  date_range: z.object({ start: z.string(), end: z.string() }).optional(),
  portfolio: z.object({
    initial_value: z.number(),
    current_value: z.number(),
    total_return_pct: z.number(),
    max_drawdown_pct: z.number(),
  }).optional(),
  cycle_level: z.object({
    n_cycles: z.number(),
    mean_return: z.number(),
    std_return: z.number(),
    sharpe_raw: z.number(),
    sharpe_adj: z.number(),
    autocorrelation: z.number(),
  }).optional(),
  daily_level: z.record(z.string(), z.object({
    n_days: z.number(),
    mean_daily_return_pct: z.number(),
    std_daily_return_pct: z.number(),
    sharpe: z.number(),
    sharpe_adj: z.number(),
    psr_gt_0: z.number(),
  }).nullable()).optional(),
  slippage: z.object({
    available: z.boolean(),
    reason: z.string().optional(),
    n_samples: z.number().optional(),
    mean_gap_pct: z.number().optional(),
    median_gap_pct: z.number().optional(),
    slippage_rms_pct: z.number().optional(),
    p90_gap_pct: z.number().optional(),
    max_gap_pct: z.number().optional(),
  }).optional(),
})

// ── Portfolio admission ────────────────────────────────────────────

export const PortfolioAdmissionSchema = z.object({
  n_intents: z.number(),
  n_admitted: z.number(),
  n_rejected: z.number(),
  budget_notional: z.number(),
  admitted: z.array(z.string()),
  rejected: z.array(z.string()),
  rejection_reasons: z.record(z.string(), z.string()).optional().default({}),
  ranking_scores: z.record(z.string(), z.number()).optional().default({}),
}).passthrough()

// ── PEK state (portfolio execution kernel) ─────────────────────────

export const PekVelocitySchema = z.object({
  pnl_velocity: z.number(),
  pnl_acceleration: z.number(),
  vol_velocity: z.number(),
  degradation_velocity: z.number(),
  execution_velocity: z.number(),
})

export const PekPerformanceStateSchema = z.object({
  outcome_scalar: z.number(),
  degradation_scalar: z.number(),
  market_scalar: z.number(),
  execution_scalar: z.number(),
  velocity_scalar: z.number(),
  composite_scalar: z.number(),
  velocity: PekVelocitySchema.optional(),
  win_rate_20: z.number(),
  consecutive_losses: z.number().int(),
  r_cumulative_20: z.number(),
  calibration_ece: z.number(),
  atr_ratio: z.number(),
  regime_label: z.string(),
  slippage_p90: z.number(),
})

export const PekRiskBudgetSchema = z.object({
  max_risk_per_trade_pct: z.number(),
  max_portfolio_heat: z.number(),
  max_concurrent_positions: z.number().int(),
  volatility_scalar: z.number(),
  drawdown_scalar: z.number(),
  performance_scalar: z.number(),
  velocity_scalar: z.number(),
})

export const PekPortfolioSnapshotSchema = z.object({
  total_equity: z.number(),
  drawdown_pct: z.number(),
  gross_exposure: z.number(),
  net_exposure: z.number(),
  open_position_count: z.number().int(),
  daily_pnl: z.number(),
  max_daily_loss: z.number(),
  drawdown_remaining: z.number(),
  leverage_remaining: z.number(),
  max_leverage: z.number(),
  concurrent_remaining: z.number().int(),
  max_concurrent: z.number().int(),
})

export const PekDataSchema = z.object({
  performance_state: PekPerformanceStateSchema.optional(),
  risk_budget: PekRiskBudgetSchema.optional(),
  portfolio_snapshot: PekPortfolioSnapshotSchema.optional(),
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
  position_concentration: PositionConcentrationSchema.optional(),
  factor_exposures: FactorExposuresSchema.optional(),
  live_sharpe: LiveSharpeSchema.optional(),
  admission: PortfolioAdmissionSchema.optional(),
  pek: PekDataSchema.optional(),
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

// ── Per-asset state sub-structures ────────────────────────────────

export const PositionSchema = z.object({
  side: z.enum(['long', 'short']),
  entry: z.number(),
  sl: z.number(),
  tp: z.number(),
  current_vol: z.number(),
  unrealized_pnl: z.number(),
  sl_mult: z.number().nullable().optional(),
  tp_mult: z.number().nullable().optional(),
})

export const ProbHistoryEntrySchema = z.object({
  date: z.string(),
  prob_long: z.number(),
  prob_short: z.number(),
  signal: z.enum(['BUY', 'SELL', 'FLAT']),
  confidence: z.number(),
  close_price: z.number(),
})

export const ScaleOutTierSchema = z.object({
  fraction: z.number(),
  price: z.number(),
  filled: z.boolean(),
  fill_price: z.number().nullable(),
})

export const MetaInferenceSchema = z.object({
  meta_confidence: z.number(),
  meta_decision: z.enum(['ENTER', 'BLOCK']),
})

export const FeatureStabilitySchema = z.object({
  jaccard_top_10: z.number().nullable(),
  spearman_rank_corr: z.number().nullable(),
  penalty: z.number(),
  window_id: z.string().nullable(),
})

export const AssetExitReasonsSchema = z.object({
  tp_rate: z.number().optional().default(0),
  sl_rate: z.number().optional().default(0),
  breakeven_rate: z.number().optional().default(0),
  flip_rate: z.number().optional().default(0),
  expiry_rate: z.number().optional().default(0),
  avg_r: z.number().optional().default(0),
})

export const ArchetypeStatsEntrySchema = z.object({
  n: z.number().int(),
  win_rate: z.number(),
  avg_r: z.number(),
  sl_rate: z.number(),
  tp_rate: z.number(),
})

export const PsiDriftFeatureSchema = z.object({
  feature: z.string(),
  psi: z.number(),
  classification: z.string(),
  trend: z.string(),
  importance_score: z.number(),
})

export const PsiDriftSchema = z.object({
  per_feature: z.array(PsiDriftFeatureSchema),
  worst_classification: z.string(),
  moderate_count: z.number().int(),
  severe_count: z.number().int(),
  psi_ok: z.boolean(),
  penalty: z.number(),
})

export const AssetMetricsSchema = z.object({
  asset: z.string(),
  current_value: z.number(),
  settled_value: z.number(),
  mtm_value: z.number(),
  total_return: z.number(),
  settled_return: z.number(),
  mtm_return: z.number(),
  drawdown: z.number(),
  profit_factor: z.number().nullable(),
  win_rate: z.number(),
  n_trades: z.number().int(),
  n_signals: z.number().int(),
  signal_distribution: z.object({
    BUY: z.number().int(),
    SELL: z.number().int(),
    FLAT: z.number().int(),
  }),
  mean_confidence: z.number(),
  mean_prob_long: z.number(),
  mean_prob_short: z.number(),
  current_price: z.number().nullable(),
  last_signal_date: z.string().nullable(),
  monthly_pf: z.number().nullable(),
  position: PositionSchema.nullable(),
  current_sl_mult: z.number(),
  current_tp_mult: z.number(),
  trade_log: z.array(z.unknown()),
  feature_stability: FeatureStabilitySchema,
  exit_reasons: AssetExitReasonsSchema,
  archetype_stats: z.record(z.string(), ArchetypeStatsEntrySchema),
  meta_inference: MetaInferenceSchema.nullable(),
  scale_out_active: z.boolean(),
  remaining_fraction: z.number(),
  scale_out_tiers: z.array(ScaleOutTierSchema).nullable(),
  psi_drift: PsiDriftSchema,
  sharpe_ratio: z.number().nullable(),
  psr_gt_0: z.number().nullable(),
  psr_gt_1: z.number().nullable(),
  min_trl: z.number().nullable(),
  crs: z.number().nullable(),
  hhi: z.number().nullable(),
})

export const AssetHaltSchema = z.object({
  halted: z.boolean(),
  reasons: z.array(z.string()),
  hard_reasons: z.array(z.string()),
  soft_warnings: z.array(z.string()),
  drawdown_ok: z.boolean(),
  monthly_pf_ok: z.boolean(),
  drought_ok: z.boolean(),
  drift_ok: z.boolean(),
  narrative_ok: z.boolean(),
  liquidity_ok: z.boolean(),
  psi_ok: z.boolean(),
})

export const RegimeGeometrySchema = z.record(
  z.string(),
  z.object({ sl_mult: z.number(), tp_mult: z.number() }),
)

export const AssetStateSchema = z.object({
  metrics: AssetMetricsSchema,
  halt: AssetHaltSchema,
  validity_state: z.string(),
  validity_exposure: z.number(),
  last_signal: ProbHistoryEntrySchema.nullable(),
  gate_override: z.boolean(),
  signal_flip: z.boolean(),
  final_signal: z.enum(['BUY', 'SELL']).nullable(),
  execution_state: z.string(),
  sl_mult: z.number(),
  tp_mult: z.number(),
  meta_confidence: z.number().nullable(),
  meta_decision: z.string().nullable(),
  feature_stability_jaccard: z.number().nullable(),
  feature_stability_spearman: z.number().nullable(),
  sell_only: z.boolean(),
  tripwire_active: z.boolean(),
  liquidity_regime: z.string(),
  liquidity_sl_mult: z.number(),
  liquidity_size_scalar: z.number(),
  narrative_sl_mult: z.number(),
  narrative_size_scalar: z.number(),
  narrative_regime: z.string().nullable(),
  narrative_stale: z.boolean(),
  regime_geometry: RegimeGeometrySchema,
  soft_warnings: z.array(z.string()),
  stop_out_last_side: z.string().nullable(),
  stop_out_last_cycle: z.number().int().nullable(),
  last_regime_long_prob: z.number().nullable(),
  last_regime_label: z.string().nullable(),
  sizing_chain: z.record(z.string(), z.union([z.number(), z.string(), z.null()])).nullable(),
  total_exits: z.number().optional().default(0),
  sl_exits: z.number().optional().default(0),
  sl_hit_rate: z.number().nullable().optional().default(null),
})

// ── Open position (per-asset with metadata) ───────────────────────

export const OpenPositionStateSchema = z.object({
  position: z.object({
    side: z.enum(['long', 'short']),
    entry: z.number(),
    sl: z.number(),
    tp: z.number(),
    entry_date: z.string(),
    vol: z.number(),
    mt5_ticket: z.union([z.string(), z.number()]).nullable(),
    layers: z.array(z.unknown()).optional(),
    avg_price: z.number().optional().default(0),
    total_size: z.number().optional().default(0),
    base_entry_size: z.number().optional().default(0),
  }),
  current_value: z.number(),
  peak_value: z.number(),
  running_mae: z.number().nullable(),
  running_mfe: z.number().nullable(),
  trade_log: z.array(z.unknown()),
  prob_history: z.array(ProbHistoryEntrySchema),
  bars_at_entry: z.number().optional().default(0),
  initial_sl: z.number().nullable().optional().default(null),
  initial_tp: z.number().nullable().optional().default(null),
})

// ── Risk signals ──────────────────────────────────────────────────

export const RiskSignalSchema = z.object({
  asset: z.string(),
  timestamp: z.string(),
  risk_level: z.enum(['LOW', 'MEDIUM', 'HIGH']),
  risk_score: z.number(),
  confidence: z.number(),
  exposure_multiplier: z.number(),
  risk_flags: z.array(z.string()),
  recommended_action: z.enum(['PAUSE', 'REDUCE_RISK', 'MONITOR', 'NORMAL']),
  explanations: z.array(z.string()),
  component_scores: z.record(z.string(), z.number()),
  drift_details: z.record(z.string(), z.unknown()),
})

// ── Shadow actions ────────────────────────────────────────────────

export const ShadowGuardrailsSchema = z.object({
  max_position_size: z.number(),
  min_hold_time: z.number().int(),
  entry_block: z.boolean(),
})

export const ShadowDriftSummarySchema = z.object({
  model: z.number(),
  signal: z.number(),
  pnl: z.number(),
  feature: z.number(),
  regime: z.number(),
})

export const ShadowActionSchema = z.object({
  asset: z.string(),
  timestamp: z.string(),
  action_type: z.enum(['PAUSE_TRADING', 'REDUCE_EXPOSURE', 'INCREASE_MONITORING', 'NONE']),
  exposure_adjustment: z.number(),
  confidence: z.number(),
  reason_codes: z.array(z.string()),
  drift_summary: ShadowDriftSummarySchema,
  recommended_guardrails: ShadowGuardrailsSchema,
})

// ── Engine snapshot ───────────────────────────────────────────────

export const EngineSnapshotSchema = z.object({
  contract_version: z.number().int().positive(),
  sequence_id: z.number().int().nonnegative(),
  schema_version: z.string().optional().default('unknown'),
  timestamp: z.string(),
  portfolio: PortfolioSummarySchema,
  assets: z.record(z.string(), AssetStateSchema),
  open_positions: z.record(z.string(), OpenPositionStateSchema).nullable().optional(),
  engine_status: EngineStatusSchema,
  halt_conditions: HaltConditionsSchema.optional().default({
    drawdown: 0,
    monthly_pf: 0,
    signal_drought: 0,
    prob_drift: 0,
  }),
  risk_signals: z.record(z.string(), RiskSignalSchema).nullable().optional(),
  shadow_actions: z.record(z.string(), ShadowActionSchema).nullable().optional(),
  risk_parity: RiskParityDataSchema.nullable().optional(),
  emergency_halt: z.boolean().optional().default(false),
  halt_reason: z.string().optional().default(''),
  halt_detail: z.string().optional().default(''),
  peak_portfolio_value: z.number().nullable().optional(),
  breaker_daily_pnl: z.array(z.number()).nullable().optional(),
})
