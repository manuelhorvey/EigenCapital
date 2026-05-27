export interface AssetExecutionQuality {
  n: number
  eis: number | null
  fqi: number | null
  avg_entry_slippage_bps: number
  avg_exit_slippage_bps: number
  avg_latency_bars: number
  gap_rate: number
  partial_fill_rate: number
  avg_fill_ratio: number
}

export interface ExecutionQualityResponse {
  by_asset: Record<string, AssetExecutionQuality>
}

export interface SlippageDistribution {
  entry_slippage: number[]
  exit_slippage: number[]
  gap_count: number
  partial_fill_count: number
  n: number
}

export interface FillQualityGaugeData {
  fqi: number
  fill_qty_ratio: number
  gap_fill: boolean
  partial_fill: boolean
  latency_bars: number
}
