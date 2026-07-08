import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useAttributionBundle } from '../useAttributionBundle'

const mockFetch = vi.fn()

vi.mock('../../lib/api', () => ({
  fetchApi: (...args: unknown[]) => mockFetch(...args),
}))

function makeQuality() {
  return {
    by_asset: {
      EURUSD: { eis: 0.82, fqi: 0.91, avg_entry_slippage_bps: 0.5, avg_exit_slippage_bps: 0.3, avg_fill_ratio: 0.98 },
      GBPUSD: { eis: 0.75, fqi: 0.85, avg_entry_slippage_bps: 1.2, avg_exit_slippage_bps: 0.8, avg_fill_ratio: 0.95 },
    },
  }
}

function makeSlippage() {
  return { n: 10, entry_slippage: [0.5, 1.2, 0.3, 2.1, 0.8], exit_slippage: [0.3, 0.8, 0.1, 1.5, 0.6] }
}

function makeSummary() {
  return {
    overall: { n_trades: 10, domain_scores: { prediction_score: 0.65, execution_score: 0.72, exit_score: 0.80, friction_score: 0.90 } },
    domain_scores: {},
  }
}

function makeWaterfall() {
  return { n: 10, net_pnl: 350.00, prediction_pnl: 500.00, execution_cost: 50.00, exit_cost: 75.00, friction_cost: 25.00 }
}

function withQueryClient() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
  return { wrapper, queryClient }
}

describe('useAttributionBundle', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('merges all four API results into a single bundle', async () => {
    mockFetch
      .mockResolvedValueOnce(makeQuality())
      .mockResolvedValueOnce(makeSlippage())
      .mockResolvedValueOnce(makeSummary())
      .mockResolvedValueOnce(makeWaterfall())

    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useAttributionBundle(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.executionQuality).toEqual(makeQuality())
    expect(result.current.data?.executionSlippage).toEqual(makeSlippage())
    expect(result.current.data?.attributionSummary).toEqual(makeSummary())
    expect(result.current.data?.attributionWaterfall).toEqual(makeWaterfall())
  })

  it('handles partial failures gracefully (null for failed endpoints)', async () => {
    mockFetch
      .mockResolvedValueOnce(makeQuality())
      .mockRejectedValueOnce(new Error('Network error'))
      .mockResolvedValueOnce(makeSummary())
      .mockRejectedValueOnce(new Error('Network error'))

    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useAttributionBundle(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.executionQuality).toEqual(makeQuality())
    expect(result.current.data?.executionSlippage).toBeNull()
    expect(result.current.data?.attributionSummary).toEqual(makeSummary())
    expect(result.current.data?.attributionWaterfall).toBeNull()
  })

  it('handles all endpoints failing', async () => {
    mockFetch.mockRejectedValue(new Error('Network error'))
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useAttributionBundle(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.executionQuality).toBeNull()
    expect(result.current.data?.executionSlippage).toBeNull()
    expect(result.current.data?.attributionSummary).toBeNull()
    expect(result.current.data?.attributionWaterfall).toBeNull()
  })
})
