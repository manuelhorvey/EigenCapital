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
  trade_log: TradeEntry[]
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
}

export interface AssetHaltConfig {
  drawdown: number
  monthly_pf: number
  signal_drought: number
  prob_drift: number
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
