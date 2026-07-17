import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { fetchApi } from '../lib/api'
import { QUERY_KEYS } from '../lib/queryKeys'
import { SystemBundleSchema } from '../lib/schemas'
import { addErrorBreadcrumb } from '../lib/errorReporting'
import { useToast } from './useToast'
import { useEffect, useRef, useState } from 'react'
import type { z } from 'zod'
type SystemBundle = z.infer<typeof SystemBundleSchema>

let _lastContractVersion: number | null = null

const LS_KEY = 'eigencapital_bundle_cache'

function saveToLocalStorage(data: SystemBundle): void {
  try {
    const slim = {
      meta: data.meta,
      snapshot: {
        contract_version: data.snapshot.contract_version,
        sequence_id: data.snapshot.sequence_id,
        schema_version: data.snapshot.schema_version,
        timestamp: data.snapshot.timestamp,
        portfolio: data.snapshot.portfolio,
        engine_status: data.snapshot.engine_status,
      },
    }
    localStorage.setItem(LS_KEY, JSON.stringify(slim))
  } catch {
    // localStorage may be full or unavailable
  }
}

function loadFromLocalStorage(): Partial<SystemBundle> | null {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return null
    return JSON.parse(raw) as Partial<SystemBundle>
  } catch {
    return null
  }
}

/** Fetches the full system bundle snapshot with optional data selector.
 *  Falls back to localStorage cache on fetch failure (offline/stale mode).
 *  Fires a persistent toast on schema validation failure. */
export function useSystemSnapshot<T = SystemBundle>(
  select?: (data: SystemBundle) => T
) {
  const { toast } = useToast()
  const [schemaFailureMsg, setSchemaFailureMsg] = useState<string | null>(null)
  const prevFailureMsg = useRef<string | null>(null)

  // Fire a persistent toast when schema validation fails
  useEffect(() => {
    if (schemaFailureMsg && schemaFailureMsg !== prevFailureMsg.current) {
      toast({
        type: 'error',
        title: 'Schema drift detected',
        message: `${schemaFailureMsg}. Dashboard may show degraded data.`,
        duration: 0,
      })
      prevFailureMsg.current = schemaFailureMsg
    }
  }, [schemaFailureMsg, toast])

  return useQuery({
    queryKey: QUERY_KEYS.system,
    queryFn: async () => {
      // Reset stale schema failure state so a recovery→relapse cycle re-fires the toast
      setSchemaFailureMsg(null)
      try {
        const json = await fetchApi<unknown>('/state-bundle.json')
        const parsed = SystemBundleSchema.passthrough().safeParse(json)
        if (parsed.success) {
          const cv = parsed.data.snapshot.contract_version
          if (_lastContractVersion !== null && _lastContractVersion !== cv) {
            console.warn(`[SNAPSHOT] Contract version mismatch: was ${_lastContractVersion}, now ${cv}. Dashboard may be incompatible with engine.`)
          }
          _lastContractVersion = cv
          saveToLocalStorage(parsed.data as unknown as SystemBundle)
          return parsed.data as unknown as SystemBundle
        }
        const driftMsg = 'Bundle validation failed — schema drift detected'
        console.error('[SNAPSHOT]', driftMsg, parsed.error.issues)
        addErrorBreadcrumb('SNAPSHOT', driftMsg)
        setSchemaFailureMsg(driftMsg)
        // Try localStorage fallback before returning empty bundle
        const cached = loadFromLocalStorage()
        if (cached?.snapshot) {
          const safe: SystemBundle = {
            meta: { ...cached.meta, status: 'degraded', server_time: new Date().toISOString() } as SystemBundle['meta'],
            snapshot: cached.snapshot as unknown as SystemBundle['snapshot'],
            live: {
              health: { fetch_time: new Date().toISOString(), fetch_age_seconds: 0, is_fresh: false, assets: {}, system_health: { mean_health_score: 0, n_assets: 0, healthiest_asset: null, weakest_asset: null, n_healthy: 0, n_degraded: 0, n_critical: 0 } },
              mt5: { fetch_time: new Date().toISOString(), fetch_age_seconds: 0, is_fresh: false, connected: false, status: 'UNKNOWN' as const, last_heartbeat: null, account: null },
            },
          }
          return safe
        }
        const safe: SystemBundle = {
          meta: { version: '1.0.0', server_time: new Date().toISOString(), status: 'degraded', snapshot_time: '', snapshot_sequence_id: 0, max_live_age_seconds: null, request_id: '' },
          snapshot: {
            contract_version: 0, sequence_id: 0, schema_version: '', timestamp: '',
            portfolio: { total_value: 0, mtm_value: 0, total_return: 0, realized_value: 0, realized_return: 0, unrealized_pnl: 0, capital: 0, allocations: {}, open_positions: 0, closed_trades: 0 },
            assets: {},
            engine_status: { initialized: false, last_update: '', start_time: '' },
            halt_conditions: { drawdown: 0, monthly_pf: 0, signal_drought: 0, prob_drift: 0 },
            emergency_halt: false, halt_reason: '', halt_detail: '',
            open_positions: null,
            risk_signals: null,
            shadow_actions: null,
            risk_parity: null,
            peak_portfolio_value: null,
            breaker_daily_pnl: null,
          },
          live: {
            health: { fetch_time: new Date().toISOString(), fetch_age_seconds: 0, is_fresh: false, assets: {}, system_health: { mean_health_score: 0, n_assets: 0, healthiest_asset: null, weakest_asset: null, n_healthy: 0, n_degraded: 0, n_critical: 0 } },
            mt5: { fetch_time: new Date().toISOString(), fetch_age_seconds: 0, is_fresh: false, connected: false, status: 'UNKNOWN' as const, last_heartbeat: null, account: null },
          },
        }
        return safe
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'unknown error'
        addErrorBreadcrumb('SNAPSHOT', `Fetch failed: ${msg}`)
        // Network error — try localStorage before throwing
        const cached = loadFromLocalStorage()
        if (cached?.snapshot) {
          const safe: SystemBundle = {
            meta: { ...cached.meta, status: 'degraded', server_time: new Date().toISOString() } as SystemBundle['meta'],
            snapshot: cached.snapshot as unknown as SystemBundle['snapshot'],
            live: {
              health: { fetch_time: new Date().toISOString(), fetch_age_seconds: 0, is_fresh: false, assets: {}, system_health: { mean_health_score: 0, n_assets: 0, healthiest_asset: null, weakest_asset: null, n_healthy: 0, n_degraded: 0, n_critical: 0 } },
              mt5: { fetch_time: new Date().toISOString(), fetch_age_seconds: 0, is_fresh: false, connected: false, status: 'UNKNOWN' as const, last_heartbeat: null, account: null },
            },
          }
          return safe
        }
        throw err
      }
    },
    refetchInterval: (q) => {
      const closed = q.state.data?.snapshot?.engine_status?.market_closed
      return closed ? 30_000 : 5_000
    },
    staleTime: 3_000,
    placeholderData: keepPreviousData,
    select,
    retry: 2,
    retryDelay: 1_000,
  })
}
