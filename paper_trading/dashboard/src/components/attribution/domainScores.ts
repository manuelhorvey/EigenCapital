import type { TradeAttributionRecord, DomainScores } from '../../types/attribution'

export function computeDomainScores(trade: TradeAttributionRecord): DomainScores {
  const { pred_confidence, pred_forecast_direction_correct, exec_entry_slippage_bps, exec_entry_timing_efficiency, exit_realized_r, exit_theoretical_r, friction_entry_slippage_bps, friction_exit_slippage_bps, friction_gap_fill, friction_partial_fill, friction_fill_qty_ratio, friction_latency_bars } = trade

  const prediction_score = pred_forecast_direction_correct === true
    ? Math.min(0.5 + pred_confidence * 0.5, 1.0)
    : pred_forecast_direction_correct === false
      ? Math.max(0, 1.0 - pred_confidence)
      : 0.5

  const efficiency = exec_entry_timing_efficiency
  const execRatio = efficiency && efficiency > 0 ? Math.min(efficiency, 1 / efficiency) : 0.5
  const slipPenalty = Math.max(0, 1 - Math.abs(exec_entry_slippage_bps) / 100)
  const execution_score = Math.min(execRatio, 1) * slipPenalty

  const exit_score = exit_theoretical_r && exit_theoretical_r !== 0
    ? Math.max(0, (Math.max(-1, Math.min(exit_realized_r / Math.abs(exit_theoretical_r), 1)) + 1) / 2)
    : 0.5

  const avgSlip = (Math.abs(friction_entry_slippage_bps ?? 0) + Math.abs(friction_exit_slippage_bps ?? 0)) / 2
  const fillRatio = friction_fill_qty_ratio ?? 1
  let friction_score = Math.max(0, 1 - avgSlip / 75) * fillRatio
  if (friction_gap_fill) friction_score *= 0.7
  if (friction_partial_fill) friction_score *= 0.85
  friction_score *= Math.max(0, 1 - (friction_latency_bars ?? 0) * 0.05)
  friction_score = Math.max(0, Math.min(1, friction_score))

  return {
    prediction_score: Math.round(prediction_score * 10000) / 10000,
    execution_score: Math.round(execution_score * 10000) / 10000,
    exit_score: Math.round(exit_score * 10000) / 10000,
    friction_score: Math.round(friction_score * 10000) / 10000,
  }
}
