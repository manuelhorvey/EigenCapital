export interface ShadowTradeRecord {
  asset: string
  side: string
  entry_price: number
  entry_date: string
  exit_price: number
  exit_date: string
  exit_reason: string
  bars_held: number
  realized_r: number
  sl_price: number
  tp_price: number
  alt_label: string
  live_exit_reason: string
  live_realized_r: number
  mae: number
  mfe: number
}

export interface ShadowDivergenceOverall {
  n: number
  divergence_rate: number
  avg_r_delta: number
  r_delta_std: number
  shadow_avg_r: number
  live_avg_r: number
  shadow_win_rate: number
  live_win_rate: number
}

export interface ShadowDivergenceByLabel {
  n: number
  divergence_rate: number
  avg_r_delta: number
  shadow_avg_r: number
  live_avg_r: number
}

export interface ShadowDivergenceSummary {
  overall: ShadowDivergenceOverall
  by_label: Record<string, ShadowDivergenceByLabel>
}
