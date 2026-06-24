import type { EngineSnapshot } from './portfolio'

export interface BundleMeta {
  version: string
  server_time: string
  status: 'ok' | 'degraded' | 'partial_failure'
  snapshot_time: string
  snapshot_sequence_id: number
  max_live_age_seconds: number | null
  request_id: string
}

export interface LiveSourceMeta {
  fetch_time: string
  fetch_age_seconds: number
  is_fresh: boolean
  error?: string
}

export interface HealthEntry {
  health_score: number
  components: Record<string, number>
}

export interface SystemHealthSummary {
  mean_health_score: number
  n_assets: number
  n_healthy: number
  n_degraded: number
  n_critical: number
  healthiest_asset: string
  weakest_asset: string
}

export interface HealthResponse {
  assets: Record<string, HealthEntry>
  system_health: SystemHealthSummary
}

export interface MT5Account {
  portfolio_value?: number
  positions?: unknown[]
  [key: string]: unknown
}

export interface MT5Status {
  connected: boolean
  status: 'CONNECTED' | 'DISCONNECTED' | 'ERROR' | 'UNKNOWN'
  last_heartbeat: string | null
  account: MT5Account | null
  [key: string]: unknown
}

export interface SystemBundle {
  meta: BundleMeta
  snapshot: EngineSnapshot
  live: {
    health: LiveSourceMeta & HealthResponse
    mt5: LiveSourceMeta & MT5Status
  }
}
