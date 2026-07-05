import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useSystemSnapshot } from '../useSystemSnapshot'

const mockFetch = vi.fn()

vi.mock('../../lib/api', () => ({
  fetchApi: (...args: unknown[]) => mockFetch(...args),
}))

function makeValidBundle(overrides: Record<string, unknown> = {}) {
  return {
    meta: {
      version: 'v1',
      server_time: '2026-07-05T00:00:00Z',
      status: 'ok',
      snapshot_time: '2026-07-05T00:00:00Z',
      snapshot_sequence_id: 42,
      max_live_age_seconds: 30,
      request_id: 'test-req',
    },
    snapshot: {
      contract_version: 7,
      sequence_id: 42,
      schema_version: '1.0.0',
      timestamp: '2026-07-05T00:00:00Z',
      portfolio: { capital: 100_000, total_value: 100_000, total_return: 0, win_rate: 0, n_trades: 0, n_signals: 0, mean_confidence: 0, mean_prob_long: 0, mean_prob_short: 0, current_price: null, last_signal_date: null, monthly_pf: null, position: null, current_sl_mult: 2, current_tp_mult: 2, trade_log: [], feature_stability: { jaccard_top_10: null, spearman_rank_corr: null, penalty: 0, window_id: null }, exit_reasons: { tp_rate: 0, sl_rate: 0, breakeven_rate: 0, flip_rate: 0, expiry_rate: 0, avg_r: 0 }, archetype_stats: {}, meta_inference: null, scale_out_active: false, remaining_fraction: 1, scale_out_tiers: null, psi_drift: { per_feature: [], worst_classification: '', moderate_count: 0, severe_count: 0, psi_ok: true, penalty: 0 }, sharpe_ratio: null, psr_gt_0: null, psr_gt_1: null, min_trl: null, crs: null, hhi: null, allocations: {}, open_positions: 0, closed_trades: 0 },
      assets: {},
      open_positions: {},
      engine_status: { initialized: true, last_update: '', start_time: '' },
      halt_conditions: { drawdown: 0, monthly_pf: 0, signal_drought: 0, prob_drift: 0 },
      ...overrides,
    },
    live: {
      health: {
        fetch_time: '2026-07-05T00:00:00Z',
        fetch_age_seconds: 0,
        is_fresh: true,
        assets: {},
        system_health: { mean_health_score: 1, n_assets: 19, n_healthy: 19, n_degraded: 0, n_critical: 0, healthiest_asset: 'GC', weakest_asset: 'GC' },
      },
      mt5: {
        fetch_time: '2026-07-05T00:00:00Z',
        fetch_age_seconds: 0,
        is_fresh: true,
        connected: true,
        status: 'CONNECTED' as const,
        last_heartbeat: '2026-07-05T00:00:00Z',
        account: { portfolio_value: 100_000 },
      },
    },
  }
}

function withQueryClient(retryOverride = false) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: retryOverride, gcTime: 0 } },
  })
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
  return { wrapper, queryClient }
}

describe('useSystemSnapshot', () => {
  beforeEach(() => {
    mockFetch.mockReset()
  })

  it('returns parsed bundle on successful fetch', async () => {
    mockFetch.mockResolvedValue(makeValidBundle())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useSystemSnapshot(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.snapshot.contract_version).toBe(7)
    expect(result.current.data?.meta.status).toBe('ok')
    expect(result.current.data?.live.mt5.connected).toBe(true)
  })

  it('falls back to raw JSON when validation fails (schema drift)', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const raw = { meta: { status: 'ok', version: 'v1', server_time: '', snapshot_time: '', snapshot_sequence_id: 0, max_live_age_seconds: null, request_id: 'x' }, snapshot: null, live: null }
    mockFetch.mockResolvedValue(raw)
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useSystemSnapshot(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(consoleSpy).toHaveBeenCalledWith(
      '[SNAPSHOT] Bundle validation failed — schema drift detected:',
      expect.any(Array),
    )
    consoleSpy.mockRestore()
  })

  it('enters error state on network failure', async () => {
    mockFetch.mockRejectedValue(new Error('Network error'))
    const { wrapper } = withQueryClient(true)
    const { result } = renderHook(() => useSystemSnapshot(), { wrapper })
    await waitFor(() => expect(result.current.isError).toBe(true), { timeout: 10_000 })
  })

  it('applies select function', async () => {
    mockFetch.mockResolvedValue(makeValidBundle())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(
      () => useSystemSnapshot((b) => b.snapshot.contract_version),
      { wrapper },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toBe(7)
  })

  it('uses 30s refetch interval when market is closed', async () => {
    mockFetch.mockResolvedValue(makeValidBundle({
      engine_status: { initialized: true, last_update: '', start_time: '', market_closed: true },
    }))
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useSystemSnapshot(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.snapshot.engine_status.market_closed).toBe(true)
  })
})
