import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useEquityHistory } from '../useEquityHistory'
import type { EquityHistoryPoint } from '../useEquityHistory'

function makeEquityPoint(overrides: Partial<Record<string, unknown>> = {}): EquityHistoryPoint {
  return {
    timestamp: '2026-07-01T00:00:00Z',
    portfolio_value: 101250,
    portfolio_return: 1.25,
    drawdown: 0.03,
    gross_exposure: 1.8,
    net_exposure: 0.6,
    assets: { EURUSD: 0.15, GBPUSD: 0.1, USDJPY: 0.08 },
    ...overrides,
  }
}

function makeEquityHistory(length = 5): EquityHistoryPoint[] {
  return Array.from({ length }, (_, i) =>
    makeEquityPoint({
      timestamp: `2026-07-${String(i + 1).padStart(2, '0')}T00:00:00Z`,
      portfolio_value: 100_000 + i * 250,
      portfolio_return: i * 0.25,
    }),
  )
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

describe('useEquityHistory', () => {
  beforeEach(() => {
    // Mock global fetch so the real createApiQuery + fetchApi work end-to-end
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(makeEquityHistory()),
    } as Response)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('returns equity history points on successful fetch', async () => {
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useEquityHistory(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(5)
    expect(result.current.data![0].portfolio_value).toBe(100_000)
    expect(result.current.data![4].portfolio_value).toBe(101_000)
  })

  it('returns points with all required fields', async () => {
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useEquityHistory(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const point = result.current.data![0]
    expect(point).toHaveProperty('timestamp')
    expect(point).toHaveProperty('portfolio_value')
    expect(point).toHaveProperty('portfolio_return')
    expect(point).toHaveProperty('drawdown')
    expect(point).toHaveProperty('gross_exposure')
    expect(point).toHaveProperty('net_exposure')
    expect(point).toHaveProperty('assets')
  })

  it('handles single data point correctly', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(makeEquityHistory(1)),
    } as Response)
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useEquityHistory(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(1)
  })

  it('handles empty equity history array', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    } as Response)
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useEquityHistory(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual([])
  })

  it('handles schema validation failure', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([{ invalid: true, timestamp: null }]),
    } as Response)
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useEquityHistory(), { wrapper })
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(consoleSpy).toHaveBeenCalledWith(
      '[equityHistory] validation failed:',
      expect.any(Array),
    )
    consoleSpy.mockRestore()
  })

  it('enters error state on network failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Network error'))
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useEquityHistory(), { wrapper })
    await waitFor(() => expect(result.current.isError).toBe(true))
  })

  it('handles drawdown values near zero', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(makeEquityHistory(3).map((p) => ({ ...p, drawdown: 0 }))),
    } as Response)
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useEquityHistory(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data![0].drawdown).toBe(0)
  })

  it('handles assets with empty record', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(makeEquityHistory(2).map((p) => ({ ...p, assets: {} }))),
    } as Response)
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useEquityHistory(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data![0].assets).toEqual({})
  })

  it('handles negative portfolio_return', async () => {
    const data = makeEquityHistory(2).map((p, i) => ({ ...p, portfolio_return: i === 1 ? -0.5 : 0 }))
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(data),
    } as Response)
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useEquityHistory(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data![1].portfolio_return).toBe(-0.5)
  })

  it('returns monotonic timestamps in order', async () => {
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useEquityHistory(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    for (let i = 1; i < result.current.data!.length; i++) {
      const prev = new Date(result.current.data![i - 1].timestamp).getTime()
      const curr = new Date(result.current.data![i].timestamp).getTime()
      expect(curr).toBeGreaterThan(prev)
    }
  })
})
