import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useTradeInspector } from '../useTradeInspector'

const mockFetch = vi.fn()

vi.mock('../../lib/api', () => ({
  fetchApi: (...args: unknown[]) => mockFetch(...args),
}))

function makeTrades() {
  const base = {
    realized_return: 0,
    pred_signal: 'BUY',
    pred_confidence: 0.7,
    pred_forecast_direction_correct: true,
    pred_regime_at_entry: 'TRENDING',
    exec_entry_type: 'MARKET',
    exec_entry_slippage_bps: 0.5,
    exec_deferred_bars: 0,
    exec_entry_timing_efficiency: null,
    exec_counterfactual_entry_timing_r: null,
    exit_theoretical_r: 3.0,
    exit_mae_per_bar: 0.1,
    exit_mfe_per_bar: 0.9,
    exit_bars_held: 48,
    exit_archetype: 'TREND',
    friction_gap_fill: false,
    friction_partial_fill: false,
    friction_counterfactual_ideal_fill_r: null,
    friction_counterfactual_real_fill_r: null,
    dq_entry_pressure_pct: null,
    dq_spread_rank: null,
    dq_volatility_rank: null,
    dq_liquidity_rank: null,
  }
  return [
    {
      ...base,
      trade_id: 't1',
      asset: 'EURUSD',
      side: 'buy',
      entry_date: '2026-07-01',
      exit_date: '2026-07-03',
      entry_price: 1.1050,
      exit_price: 1.1080,
      exit_realized_r: 2.5,
      realized_pnl: 150.00,
      exit_mae: 0.3,
      exit_mfe: 2.8,
      pred_archetype_at_entry: 'MOMENTUM',
      friction_entry_slippage_bps: 0.5,
      friction_exit_slippage_bps: 0.3,
      friction_fill_qty_ratio: 0.98,
      friction_latency_bars: 1,
      exit_exit_reason: 'TP',
    },
    {
      ...base,
      trade_id: 't2',
      asset: 'GBPUSD',
      side: 'sell',
      entry_date: '2026-07-02',
      exit_date: '2026-07-04',
      entry_price: 1.2650,
      exit_price: 1.2610,
      exit_realized_r: 1.8,
      realized_pnl: 200.00,
      exit_mae: 0.5,
      exit_mfe: 2.1,
      pred_archetype_at_entry: 'BREAKOUT',
      friction_entry_slippage_bps: 1.2,
      friction_exit_slippage_bps: 0.8,
      friction_fill_qty_ratio: 1.0,
      friction_latency_bars: 2,
      exit_exit_reason: 'TP',
    },
  ]
}

function withQueryClient() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
  return { wrapper, queryClient }
}

describe('useTradeInspector', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns null when no asset provided', async () => {
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useTradeInspector(), { wrapper })
    expect(result.current).toBeNull()
  })

  it('returns null when asset not found', async () => {
    mockFetch.mockResolvedValue(makeTrades())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useTradeInspector('USDJPY'), { wrapper })
    await waitFor(() => expect(result.current).toBeNull())
  })

  it('finds matching trade by asset name', async () => {
    mockFetch.mockResolvedValue(makeTrades())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useTradeInspector('EURUSD'), { wrapper })
    await waitFor(() => {
      expect(result.current).not.toBeNull()
      expect(result.current!.basic.asset).toBe('EURUSD')
    })
  })

  it('filters by entry date when provided', async () => {
    mockFetch.mockResolvedValue(makeTrades())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useTradeInspector('EURUSD', '2026-07-01'), { wrapper })
    await waitFor(() => {
      expect(result.current).not.toBeNull()
      expect(result.current!.basic.entry_date).toBe('2026-07-01')
    })
  })

  it('returns basic + attribution data for matched trade', async () => {
    mockFetch.mockResolvedValue(makeTrades())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useTradeInspector('GBPUSD'), { wrapper })
    await waitFor(() => {
      expect(result.current).not.toBeNull()
      expect(result.current!.basic.realized_r).toBe(1.8)
      expect(result.current!.basic.realized_pnl).toBe(200.00)
      expect(result.current!.attribution).not.toBeNull()
      expect(result.current!.attribution!.asset).toBe('GBPUSD')
    })
  })

  it('returns null when dates do not match', async () => {
    mockFetch.mockResolvedValue(makeTrades())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useTradeInspector('EURUSD', '2099-01-01'), { wrapper })
    await waitFor(() => expect(result.current).toBeNull())
  })
})
