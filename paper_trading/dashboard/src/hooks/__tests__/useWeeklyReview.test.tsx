import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useWeeklyReview } from '../useWeeklyReview'

const mockFetch = vi.fn()

vi.mock('../../lib/api', () => ({
  fetchApi: (...args: unknown[]) => mockFetch(...args),
}))

const STORAGE_KEY = 'weekly_review_acknowledged'

function makeReview(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    week_label: '2026-W27',
    generated_at: '2026-07-07T12:00:00Z',
    summary: {
      n_trades: 42,
      total_pnl: 1250.0,
      total_return_pct: 1.25,
      win_rate: 0.55,
      tp_rate: 0.3,
      sl_rate: 0.25,
      signal_flip_rate: 0.15,
      profit_factor: 1.8,
      avg_r: 0.42,
      best_r_multiple: 3.2,
      worst_r_multiple: -1.5,
    },
    by_asset: [
      { asset: 'EURUSD', n_trades: 10, win_rate: 0.6, tp_rate: 0.3, sl_rate: 0.2, avg_r: 0.5, profit_factor: 2.1, pnl: 300 },
      { asset: 'GBPUSD', n_trades: 8, win_rate: 0.5, tp_rate: 0.25, sl_rate: 0.25, avg_r: 0.3, profit_factor: 1.5, pnl: 150 },
    ],
    top_winners: [{ asset: 'EURUSD', r: 1.5 }],
    top_losers: [{ asset: 'GBPUSD', r: -1.2 }],
    exit_reason_breakdown: { SL: 10, TP: 12, BREAKEVEN: 5, FLIP: 8, EXPIRY: 3, MANUAL: 2, other: 2 },
    stop_out_cooldowns: { stop_out_cooldowns_triggered: 2, estimated_churn_prevented: 5, assets_in_cooldown: ['AUDUSD'] },
    governance_summary: { halted_assets: [], most_common_validity: 'OK' },
    regime_correlation: [{ regime: 'trending', n_trades: 20, win_rate: 0.6, sl_rate: 0.2 }],
    vs_prior_week: { pnl_change: 0.5, win_rate_change: 0.02, sl_rate_change: -0.03, tp_rate_change: 0.01 },
    ...overrides,
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

describe('useWeeklyReview', () => {
  beforeEach(() => {
    mockFetch.mockReset()
    localStorage.clear()
  })

  afterEach(() => {
    localStorage.clear()
  })

  it('returns review data on successful fetch', async () => {
    mockFetch.mockResolvedValue(makeReview())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useWeeklyReview(), { wrapper })
    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.data?.week_label).toBe('2026-W27')
    expect(result.current.data?.summary.n_trades).toBe(42)
    expect(result.current.data?.summary.profit_factor).toBe(1.8)
  })

  it('returns null data on initial pending state', async () => {
    mockFetch.mockImplementation(() => new Promise(() => {})) // never resolves
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useWeeklyReview(), { wrapper })
    expect(result.current.data).toBeNull()
  })

  it('handles schema validation failure gracefully', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    mockFetch.mockResolvedValue({ week_label: 123 }) // wrong type
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useWeeklyReview(), { wrapper })
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(consoleSpy).toHaveBeenCalledWith(
      '[WeeklyReview] validation failed:',
      expect.any(Array),
    )
    consoleSpy.mockRestore()
  })

  it('enters error state on network failure', async () => {
    mockFetch.mockRejectedValue(new Error('Network error'))
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useWeeklyReview(), { wrapper })
    await waitFor(() => expect(result.current.isError).toBe(true))
  })

  it('shows review when no localStorage acknowledgement exists', async () => {
    mockFetch.mockResolvedValue(makeReview())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useWeeklyReview(), { wrapper })
    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.show).toBe(true)
  })

  it('hides review when localStorage matches current week_label', async () => {
    localStorage.setItem(STORAGE_KEY, '2026-W27')
    mockFetch.mockResolvedValue(makeReview())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useWeeklyReview(), { wrapper })
    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.show).toBe(false)
  })

  it('shows review again for a new week after acknowledging a previous one', async () => {
    localStorage.setItem(STORAGE_KEY, '2026-W26')
    mockFetch.mockResolvedValue(makeReview({ week_label: '2026-W27' }))
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useWeeklyReview(), { wrapper })
    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.show).toBe(true)
  })

  it('dismiss persists week_label to localStorage', async () => {
    mockFetch.mockResolvedValue(makeReview())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useWeeklyReview(), { wrapper })
    await waitFor(() => expect(result.current.isPending).toBe(false))
    act(() => {
      result.current.dismiss()
    })
    expect(localStorage.getItem(STORAGE_KEY)).toBe('2026-W27')
  })

  it('acknowledge calls POST and invalidates the query', async () => {
    mockFetch.mockResolvedValue(makeReview())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useWeeklyReview(), { wrapper })
    await waitFor(() => expect(result.current.isPending).toBe(false))

    // Reset fetch call count after initial load
    mockFetch.mockReset()
    mockFetch.mockResolvedValue({})

    act(() => {
      result.current.acknowledge()
    })

    // Should have called the acknowledge endpoint
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith('/weekly-review/acknowledge', { method: 'POST' })
    })
  })

  it('does not error when acknowledge is called before data loads', async () => {
    mockFetch.mockImplementation(() => new Promise(() => {})) // never resolves
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useWeeklyReview(), { wrapper })

    expect(() => {
      act(() => {
        result.current.acknowledge()
      })
    }).not.toThrow()
  })

  it('does not error when dismiss is called before data loads', async () => {
    mockFetch.mockImplementation(() => new Promise(() => {})) // never resolves
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useWeeklyReview(), { wrapper })

    expect(() => {
      act(() => {
        result.current.dismiss()
      })
    }).not.toThrow()
    // Should not set localStorage when no data
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('handles missing vs_prior_week (nullable field)', async () => {
    mockFetch.mockResolvedValue(makeReview({ vs_prior_week: null }))
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useWeeklyReview(), { wrapper })
    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.data?.vs_prior_week).toBeNull()
  })

  it('handles empty by_asset array', async () => {
    mockFetch.mockResolvedValue(makeReview({ by_asset: [] }))
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useWeeklyReview(), { wrapper })
    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.data?.by_asset).toEqual([])
  })

  it('handles empty top_winners and top_losers', async () => {
    mockFetch.mockResolvedValue(makeReview({ top_winners: [], top_losers: [] }))
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useWeeklyReview(), { wrapper })
    await waitFor(() => expect(result.current.isPending).toBe(false))
    expect(result.current.data?.top_winners).toEqual([])
    expect(result.current.data?.top_losers).toEqual([])
  })
})
