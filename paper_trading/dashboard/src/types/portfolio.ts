export interface ProbHistoryEntry {
  date: string
  prob_long: number
  prob_short: number
  signal: 'BUY' | 'SELL' | 'FLAT'
  confidence: number
  close_price: number
}

export interface OpenPositionState {
  position: Position & { entry_date: string; vol: number; mt5_ticket: string | number | null; layers?: unknown[]; avg_price: number; total_size: number; base_entry_size: number }
  current_value: number
  peak_value: number
  running_mae: number | null
  running_mfe: number | null
  trade_log: TradeEntry[]
  prob_history: ProbHistoryEntry[]
  bars_at_entry: number
  initial_sl: number | null
  initial_tp: number | null
  adaptive_exit_phase?: string
  peak_mfe_r?: number | null
  sl_update_count?: number
}

export interface RiskSignal {
  asset: string
  timestamp: string
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH'
  risk_score: number
  confidence: number
  exposure_multiplier: number
  risk_flags: string[]
  recommended_action: 'PAUSE' | 'REDUCE_RISK' | 'MONITOR' | 'NORMAL'
  explanations: string[]
  component_scores: Record<string, number>
  drift_details: Record<string, unknown>
}

export interface ShadowAction {
  asset: string
  timestamp: string
  action_type: 'PAUSE_TRADING' | 'REDUCE_EXPOSURE' | 'INCREASE_MONITORING' | 'NONE'
  exposure_adjustment: number
  confidence: number
  reason_codes: string[]
  drift_summary: {
    model: number
    signal: number
    pnl: number
    feature: number
    regime: number
  }
  recommended_guardrails: {
    max_position_size: number
    min_hold_time: number
    entry_block: boolean
  }
}

export interface EngineSnapshot {
  contract_version: number
  sequence_id: number
  schema_version: string
  timestamp: string
  portfolio: Portfolio
  assets: Record<string, AssetState>
  open_positions?: Record<string, OpenPositionState>
  engine_status: EngineStatus
  halt_conditions: HaltConditions
  risk_signals?: Record<string, RiskSignal> | null
  shadow_actions?: Record<string, ShadowAction> | null
  risk_parity?: Record<string, unknown> | null
  emergency_halt?: boolean
  halt_reason?: string
  halt_detail?: string
  peak_portfolio_value?: number | null
  breaker_daily_pnl?: number[] | null
}

export interface PositionConcentration {
  long: number
  short: number
  total: number
  skew: number
  dominant_side: string
  threshold: number
  alert: boolean
}

export interface FactorExposures {
  exposures: Record<string, number>
  violations: Record<string, { exposure: number; limit_lo: number; limit_hi: number; violation: string | null }>
  n_violations: number
  within_limits: boolean
}

export interface LiveSharpeData {
  available: boolean
  reason?: string
  n_cycles?: number
  n_days?: number
  date_range?: { start: string; end: string }
  portfolio?: {
    initial_value: number
    current_value: number
    total_return_pct: number
    max_drawdown_pct: number
  }
  cycle_level?: {
    n_cycles: number
    mean_return: number
    std_return: number
    sharpe_raw: number
    sharpe_adj: number
    autocorrelation: number
  }
  daily_level?: Record<string, {
    n_days: number
    mean_daily_return_pct: number
    std_daily_return_pct: number
    sharpe: number
    sharpe_adj: number
    psr_gt_0: number
  } | null>
  slippage?: {
    available: boolean
    reason?: string
    n_samples?: number
    mean_gap_pct?: number
    median_gap_pct?: number
    slippage_rms_pct?: number
    p90_gap_pct?: number
    max_gap_pct?: number
  }
}

export interface PortfolioAdmission {
  n_intents: number
  n_admitted: number
  n_rejected: number
  budget_notional: number
  admitted: string[]
  rejected: string[]
  rejection_reasons: Record<string, string>
  ranking_scores: Record<string, number>
}

export interface PekVelocity {
  pnl_velocity: number
  pnl_acceleration: number
  vol_velocity: number
  degradation_velocity: number
  execution_velocity: number
}

export interface PekPerformanceState {
  outcome_scalar: number
  degradation_scalar: number
  market_scalar: number
  execution_scalar: number
  velocity_scalar: number
  composite_scalar: number
  velocity?: PekVelocity
  win_rate_20: number
  consecutive_losses: number
  r_cumulative_20: number
  calibration_ece: number
  atr_ratio: number
  regime_label: string
  slippage_p90: number
}

export interface PekRiskBudget {
  max_risk_per_trade_pct: number
  max_portfolio_heat: number
  max_concurrent_positions: number
  volatility_scalar: number
  drawdown_scalar: number
  performance_scalar: number
  velocity_scalar: number
}

export interface PekPortfolioSnapshot {
  total_equity: number
  drawdown_pct: number
  gross_exposure: number
  net_exposure: number
  open_position_count: number
  daily_pnl: number
  daily_loss_remaining: number
  max_daily_loss: number
  drawdown_remaining: number
  leverage_remaining: number
  max_leverage: number
  concurrent_remaining: number
  max_concurrent: number
}

export interface PekData {
  performance_state?: PekPerformanceState
  risk_budget?: PekRiskBudget
  portfolio_snapshot?: PekPortfolioSnapshot
}

export interface Portfolio {
  total_value: number
  mtm_value: number
  total_return: number
  realized_value: number
  realized_return: number
  unrealized_pnl: number
  days_running: number
  runtime_hours: number
  start_date: string
  start_datetime: string
  last_update: string
  capital: number
  allocations: Record<string, number>
  deployment_cleared: boolean
  open_positions: number
  closed_trades: number
  execution_state?: string
  average_validity_exposure?: number
  portfolio_drawdown?: number
  portfolio_peak_value?: number | null
  position_concentration?: PositionConcentration
  factor_exposures?: FactorExposures
  live_sharpe?: LiveSharpeData
  admission?: PortfolioAdmission
  pek?: PekData
  edge_health?: EdgeHealthSummary
}

export interface EdgeHealthSummary {
  reversal_rate: number | null
  n_losers: number
  n_trades: number
  mean_mfe_r: number | null
  median_mfe_r: number | null
  alert: boolean
}

export interface FeatureStability {
  jaccard_top_10: number | null
  spearman_rank_corr: number | null
  penalty: number
  window_id: string | null
}

export interface MetaInference {
  meta_confidence: number
  meta_decision: 'ENTER' | 'BLOCK'
}

export interface PsiDrift {
  per_feature: PsiDriftFeature[]
  worst_classification: string
  moderate_count: number
  severe_count: number
  psi_ok: boolean
  penalty: number
}

export interface PsiDriftFeature {
  feature: string
  psi: number
  classification: string
  trend: string
  importance_score: number
}

export interface ArchetypeStatsEntry {
  n: number
  win_rate: number
  avg_r: number
  sl_rate: number
  tp_rate: number
}

export interface AssetState {
  metrics: AssetMetrics
  halt: AssetHaltConfig
  validity_state: string
  validity_exposure: number
  last_signal: LastSignal | null
  gate_override: boolean
  signal_flip: boolean
  final_signal: 'BUY' | 'SELL' | null
  execution_state: string
  sl_mult: number
  tp_mult: number
  meta_confidence: number | null
  meta_decision: string | null
  feature_stability_jaccard: number | null
  feature_stability_spearman: number | null
  sell_only: boolean
  tripwire_active: boolean
  liquidity_regime: string
  liquidity_sl_mult: number
  liquidity_size_scalar: number
  narrative_sl_mult: number
  narrative_size_scalar: number
  narrative_regime: string | null
  narrative_stale: boolean
  regime_geometry: Record<string, { sl_mult: number; tp_mult: number }>
  soft_warnings: string[]
  stop_out_last_side: string | null
  stop_out_last_cycle: number | null
  last_regime_long_prob: number | null
  last_regime_label: string | null
  sizing_chain: Record<string, number | string | null> | null
  total_exits: number
  sl_exits: number
  sl_hit_rate: number | null
}

export interface ExitReasons {
  tp_rate: number
  sl_rate: number
  breakeven_rate: number
  flip_rate: number
  expiry_rate: number
  avg_r: number
}

export interface ScaleOutTierInfo {
  fraction: number
  price: number
  filled: boolean
  fill_price: number | null
}

export interface AssetMetrics {
  asset: string
  current_value: number
  settled_value: number
  mtm_value: number
  total_return: number
  settled_return: number
  mtm_return: number
  drawdown: number
  profit_factor: number | null
  win_rate: number
  n_trades: number
  n_signals: number
  signal_distribution: SignalDistribution
  mean_confidence: number
  mean_prob_long: number
  mean_prob_short: number
  current_price: number | null
  last_signal_date: string | null
  monthly_pf: number | null
  position: Position | null
  current_sl_mult: number
  current_tp_mult: number
  trade_log: TradeEntry[]
  feature_stability: FeatureStability
  exit_reasons: ExitReasons
  archetype_stats: Record<string, ArchetypeStatsEntry>
  meta_inference: MetaInference | null
  scale_out_active: boolean
  remaining_fraction: number
  scale_out_tiers: ScaleOutTierInfo[] | null
  psi_drift: PsiDrift
  sharpe_ratio: number | null
  psr_gt_0: number | null
  psr_gt_1: number | null
  min_trl: number | null
  crs: number | null
  hhi: number | null
}

export interface SignalDistribution {
  BUY: number
  SELL: number
  FLAT: number
}

export interface LastSignal {
  date: string
  prob_long: number
  prob_short: number
  signal: 'BUY' | 'SELL' | 'FLAT'
  confidence: number
  close_price: number
}

export interface Layer {
  entry_price: number
  size: number
  timestamp: string
  signal_id: string
  pnl_at_time: number
}

export interface Position {
  side: 'long' | 'short'
  entry: number
  sl: number
  tp: number
  current_vol: number
  unrealized_pnl: number
  sl_mult?: number
  tp_mult?: number
  layers?: Layer[]
}

export interface AssetHaltConfig {
  halted: boolean
  reasons: string[]
  hard_reasons: string[]
  soft_warnings: string[]
  drawdown_ok: boolean
  monthly_pf_ok: boolean
  drought_ok: boolean
  drift_ok: boolean
  narrative_ok: boolean
  liquidity_ok: boolean
  psi_ok: boolean
}

export interface HaltConditions {
  drawdown: number
  monthly_pf: number
  signal_drought: number
  prob_drift: number
}

export interface EngineStatus {
  initialized: boolean
  last_update: string
  start_time: string
  market_closed?: boolean
}

export interface TradeEntry {
  asset: string
  side: string
  entry: number
  exit: number
  return: number
  reason: string
  entry_date: string
  exit_date: string
  bars?: number
}

export interface EquityHistoryPoint {
  timestamp: string
  portfolio_value: number
  portfolio_return: number
  drawdown: number
  gross_exposure: number
  net_exposure: number
  assets: Record<string, number>
}

export interface ConfidenceBucket {
  asset: string
  date: string
  mean_conf: number
  n_signals: number
  count_30_40?: number
  count_40_50?: number
  count_50_60?: number
  count_60_70?: number
  count_70_80?: number
}

export interface VolRegime {
  asset: string
  training_vol: number
  current_vol: number
  ratio: number
  status: 'green' | 'amber' | 'red'
}

export interface WeeklyReviewSummary {
  n_trades: number
  total_pnl: number
  total_return_pct: number
  win_rate: number
  tp_rate: number
  sl_rate: number
  signal_flip_rate: number
  profit_factor: number | null
  avg_r: number
  best_r_multiple: number
  worst_r_multiple: number
}

export interface WeeklyReviewByAsset {
  asset: string
  n_trades: number
  win_rate: number
  tp_rate: number
  sl_rate: number
  avg_r: number
  profit_factor: number | null
  pnl: number
}

export interface WeeklyReviewExitBreakdown {
  SL: number
  TP: number
  BREAKEVEN: number
  FLIP: number
  EXPIRY: number
  MANUAL: number
  other: number
}

export interface WeeklyReviewStopOut {
  stop_out_cooldowns_triggered: number
  estimated_churn_prevented: number
  assets_in_cooldown: string[]
}

export interface WeeklyReviewGovernance {
  halted_assets: string[]
  most_common_validity: string
}

export interface WeeklyReviewRegimeCorrelation {
  regime: string
  n_trades: number
  win_rate: number
  sl_rate: number
}

export interface WeeklyReviewVsPrior {
  pnl_change: number
  win_rate_change: number
  sl_rate_change: number
  tp_rate_change: number
}

export interface WeeklyReview {
  week_label: string
  generated_at: string
  summary: WeeklyReviewSummary
  by_asset: WeeklyReviewByAsset[]
  top_winners: Record<string, unknown>[]
  top_losers: Record<string, unknown>[]
  exit_reason_breakdown: WeeklyReviewExitBreakdown
  stop_out_cooldowns: WeeklyReviewStopOut
  governance_summary: WeeklyReviewGovernance
  regime_correlation: WeeklyReviewRegimeCorrelation[]
  vs_prior_week: WeeklyReviewVsPrior | null
}
