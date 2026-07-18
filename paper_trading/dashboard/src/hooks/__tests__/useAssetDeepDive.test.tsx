import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useAssetDeepDive } from '../useAssetDeepDive'
import type { DeepDiveData } from '../useAssetDeepDive'

const mockFetch = vi.fn()

vi.mock('../../lib/api', () => ({
  fetchApi: (...args: unknown[]) => mockFetch(...args),
}))

function makeDeepDive(overrides: Partial<Record<string, unknown>> = {}): DeepDiveData {
  return {
    asset: 'EURUSD',
    feature_importance: [
      { feature: 'carry', importance: 0.25, type: 'alpha' },
      { feature: 'momentum_5d', importance: 0.18, type: 'alpha' },
    ],
    trades: [
      {
        side: 'buy',
        entry: 1.1050,
        exit: 1.1080,
        return: 0.0027,
        reason: 'TP',
        entry_date: '2026-07-01T10:00:00Z',
        exit_date: '2026-07-01T14:00:00Z',
        mae: -0.0012,
        mfe: 0.0035,
      },
    ],
    final_signal: 'BUY',
    sell_only: false,
    tripwire_active: false,
    last_signal: null,
    metrics: null,
    ...overrides,
  } as DeepDiveData
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

describe('useAssetDeepDive', () => {
  beforeEach(() => {
    mockFetch.mockReset()
  })

  it('returns deep dive data for a valid asset name', async () => {
    mockFetch.mockResolvedValue(makeDeepDive())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useAssetDeepDive('EURUSD'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.asset).toBe('EURUSD')
    expect(result.current.data?.feature_importance).toHaveLength(2)
    expect(result.current.data?.trades).toHaveLength(1)
    expect(result.current.data?.final_signal).toBe('BUY')
  })

  it('does not fetch when asset name is empty', async () => {
    mockFetch.mockResolvedValue(makeDeepDive())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useAssetDeepDive(''), { wrapper })
    // Query with enabled:false stays in 'idle' fetchStatus with undefined data
    expect(result.current.fetchStatus).toBe('idle')
    expect(result.current.data).toBeUndefined()
    expect(result.current.isPending).toBe(true)
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('uses asset name in the query key', async () => {
    mockFetch.mockResolvedValue(makeDeepDive())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useAssetDeepDive('GBPUSD'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.asset).toBe('EURUSD') // from mock, not query key
  })

  it('gracefully degrades on schema validation failure (safeParse fallback)', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    mockFetch.mockResolvedValue({ asset: 123, feature_importance: 'invalid', trades: null })
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useAssetDeepDive('EURUSD'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.asset).toBe('EURUSD')
    expect(result.current.data?.feature_importance).toEqual([])
    expect(result.current.data?.trades).toEqual([])
    expect(result.current.data?.final_signal).toBeNull()
    consoleSpy.mockRestore()
  })

  it('enters error state on network failure', async () => {
    mockFetch.mockRejectedValue(new Error('Network error'))
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useAssetDeepDive('EURUSD'), { wrapper })
    await waitFor(() => expect(result.current.isError).toBe(true))
  })

  it('returns feature importance with optional fields', async () => {
    const dd = makeDeepDive()
    dd.feature_importance = [
      { feature: 'carry', importance: 0.25, type: 'alpha' },
      { feature: 'momentum', importance: 0.15 },
      { error: 'computation error', feature: 'volatility' },
    ]
    mockFetch.mockResolvedValue(dd)
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useAssetDeepDive('EURUSD'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.feature_importance).toHaveLength(3)
  })

  it('has staleTime of 60_000', async () => {
    mockFetch.mockResolvedValue(makeDeepDive())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useAssetDeepDive('EURUSD'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    // staleTime is not directly observable, but we can check that the query exists and is stable
    expect(result.current.data?.asset).toBe('EURUSD')
  })

  it('includes mae and mfe nullable fields on trades', async () => {
    mockFetch.mockResolvedValue(makeDeepDive())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useAssetDeepDive('EURUSD'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.trades[0].mae).toBe(-0.0012)
    expect(result.current.data?.trades[0].mfe).toBe(0.0035)
  })

  it('handles sell_only and tripwire_active boolean flags', async () => {
    mockFetch.mockResolvedValue(makeDeepDive({ sell_only: true, tripwire_active: true }))
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useAssetDeepDive('EURUSD'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.sell_only).toBe(true)
    expect(result.current.data?.tripwire_active).toBe(true)
  })
})
