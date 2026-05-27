export interface TradeAttributionRecord {
  trade_id: string
  asset: string
  entry_date: string
  exit_date: string
  side: string
  entry_price: number
  exit_price: number
  realized_return: number
  realized_pnl: number

  pred_signal: string
  pred_confidence: number
  pred_forecast_direction_correct: boolean | null
  pred_archetype_at_entry: string
  pred_regime_at_entry: string

  exec_entry_type: string
  exec_entry_slippage_bps: number
  exec_deferred_bars: number
  exec_entry_timing_efficiency: number | null
  exec_counterfactual_entry_timing_r: number | null

  exit_exit_reason: string
  exit_realized_r: number
  exit_theoretical_r: number
  exit_mae: number
  exit_mfe: number
  exit_mae_per_bar: number
  exit_mfe_per_bar: number
  exit_bars_held: number
  exit_archetype: string

  friction_entry_slippage_bps: number
  friction_exit_slippage_bps: number
  friction_gap_fill: boolean
  friction_partial_fill: boolean
  friction_fill_qty_ratio: number
  friction_latency_bars: number
  friction_counterfactual_ideal_fill_r: number | null
  friction_counterfactual_real_fill_r: number | null

  dq_entry_pressure_pct: number | null
  dq_spread_rank: number | null
  dq_volatility_rank: number | null
  dq_liquidity_rank: number | null
}

export interface DomainScores {
  prediction_score: number
  execution_score: number
  exit_score: number
  friction_score: number
}

export interface AttributionSummary {
  overall: {
    n_trades: number
    avg_r: number
    avg_mae_pct: number
    avg_mfe_pct: number
    domain_scores: DomainScores
  }
  by_archetype: Record<string, {
    n: number
    avg_mae_pct: number
    avg_mfe_pct: number
    avg_mfe_mae_ratio: number
  }>
  by_regime: Record<string, {
    n: number
    avg_mae_pct: number
    avg_mfe_pct: number
    avg_mfe_mae_ratio: number
  }>
  domain_scores: Record<string, DomainScores>
}

export interface AttributionWaterfall {
  prediction_pnl: number
  execution_cost: number
  exit_cost: number
  friction_cost: number
  net_pnl: number
  n: number
}
