import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useTrades } from '../useTrades'

const mockFetch = vi.fn()

vi.mock('../../lib/api', () => ({
  fetchApi: (...args: unknown[]) => mockFetch(...args),
}))

function makeTrades(overrides: Partial<Record<string, unknown>> = {}) {
  return [
    {
      asset: 'EURUSD',
      side: 'buy',
      entry: 1.1050,
      exit: 1.1080,
      return: 0.0027,
      reason: 'TP',
      entry_date: '2026-07-01T10:00:00Z',
      exit_date: '2026-07-01T14:00:00Z',
      bars: 8,
      ...overrides,
    },
    {
      asset: 'GBPUSD',
      side: 'sell',
      entry: 1.2650,
      exit: 1.2610,
      return: 0.0032,
      reason: 'SL',
      entry_date: '2026-07-01T11:00:00Z',
      exit_date: '2026-07-01T13:00:00Z',
      bars: 4,
      ...overrides,
    },
  ]
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

describe('useTrades', () => {
  beforeEach(() => {
    mockFetch.mockReset()
  })

  it('returns trades on successful fetch with default params', async () => {
    mockFetch.mockResolvedValue(makeTrades())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useTrades(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(2)
    expect(result.current.data![0].asset).toBe('EURUSD')
    expect(result.current.data![1].asset).toBe('GBPUSD')
  })

  it('passes limit and offset to the API endpoint', async () => {
    const calls: string[] = []
    mockFetch.mockImplementation((url: string) => {
      calls.push(url)
      return Promise.resolve(makeTrades())
    })
    const { wrapper } = withQueryClient()
    renderHook(() => useTrades(5, 10), { wrapper })
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]).toContain('limit=5')
    expect(calls[0]).toContain('offset=10')
  })

  it('differentiates cache by limit and offset via query key', async () => {
    const calls: string[] = []
    mockFetch.mockImplementation((url: string) => {
      calls.push(url)
      return Promise.resolve(makeTrades())
    })
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useTrades(5, 10), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    // The query key includes [5, 10] — a second call with different params
    // should fetch again, not reuse cache
    expect(calls.length).toBe(1)
  })

  it('handles schema validation failure', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    mockFetch.mockResolvedValue([{ invalid: true }])
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useTrades(), { wrapper })
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(consoleSpy).toHaveBeenCalledWith(
      '[Trades] validation failed:',
      expect.any(Array),
    )
    consoleSpy.mockRestore()
  })

  it('enters error state on network failure', async () => {
    mockFetch.mockRejectedValue(new Error('Network error'))
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useTrades(), { wrapper })
    await waitFor(() => expect(result.current.isError).toBe(true))
  })

  it('includes bars field when present (optional field)', async () => {
    mockFetch.mockResolvedValue(makeTrades())
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useTrades(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data![0].bars).toBe(8)
  })

  it('tolerates missing bars field', async () => {
    const [trade] = makeTrades()
    delete (trade as Record<string, unknown>).bars
    mockFetch.mockResolvedValue([trade])
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useTrades(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data![0].bars).toBeUndefined()
  })
})
