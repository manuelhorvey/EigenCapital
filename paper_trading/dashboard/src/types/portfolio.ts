export interface ProbHistoryEntry {
  date: string
  prob_long: number
  prob_short: number
  signal: 'BUY' | 'SELL' | 'FLAT'
  confidence: number
  close_price: number
}

export interface OpenPositionState {
  position: Position & { entry_date: string; vol: number }
  current_value: number
  peak_value: number
  trade_log: TradeEntry[]
  prob_history: ProbHistoryEntry[]
}

export interface EngineSnapshot {
  schema_version: string
  timestamp: string
  portfolio: Portfolio
  assets: Record<string, AssetState>
  open_positions?: Record<string, OpenPositionState>
  engine_status: EngineStatus
  halt_conditions: HaltConditions
  risk_signals?: Record<string, unknown>
  shadow_actions?: Record<string, unknown>
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
}

export interface AssetState {
  metrics: AssetMetrics
  halt: AssetHaltConfig
  validity_state: string
  validity_exposure?: number
  last_signal: LastSignal
  execution_state?: string
  sl_mult?: number
  tp_mult?: number
  meta_confidence?: number
  meta_decision?: string
  feature_stability_jaccard?: number
  feature_stability_spearman?: number
  sell_only?: boolean
  tripwire_active?: boolean
}

export interface ExitReasons {
  tp_rate: number
  sl_rate: number
  signal_flip_rate: number
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
  mtm_value: number
  total_return: number
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
  current_price: number
  last_signal_date: string
  monthly_pf: number | null
  position: Position | null
  current_sl_mult?: number
  current_tp_mult?: number
  trade_log: TradeEntry[]
  exit_reasons?: ExitReasons
  scale_out_active?: boolean
  remaining_fraction?: number
  scale_out_tiers?: ScaleOutTierInfo[] | null
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

export interface Position {
  side: 'long' | 'short'
  entry: number
  sl: number
  tp: number
  current_vol: number
  unrealized_pnl: number
  sl_mult?: number
  tp_mult?: number
}

export interface AssetHaltConfig {
  drawdown: number
  monthly_pf: number
  signal_drought: number
  prob_drift: number
  halted?: boolean
  reasons?: string[]
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
