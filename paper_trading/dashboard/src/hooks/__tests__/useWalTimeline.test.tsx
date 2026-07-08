import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useWalTimeline, groupWalEvents } from '../useWalTimeline'
import type { WalEvent } from '../useWalTimeline'

const mockFetch = vi.fn()

vi.mock('../../lib/api', () => ({
  fetchApi: (...args: unknown[]) => mockFetch(...args),
}))

function makeWalResponse(asset: string) {
  return {
    events: [
      { sequence: 1, timestamp: '2026-07-05T00:00:01Z', event_type: 'features_snapshot', payload: { feature_hash: 'abc123' } },
      { sequence: 2, timestamp: '2026-07-05T00:00:02Z', event_type: 'inference_output', payload: { feature_hash: 'abc123' } },
      { sequence: 3, timestamp: '2026-07-05T00:00:03Z', event_type: 'features_snapshot', payload: { feature_hash: 'def456' } },
    ],
    total: 3,
    asset,
  }
}

function withQueryClient() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
  return { wrapper, queryClient }
}

describe('useWalTimeline', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches and returns WAL events for a given asset', async () => {
    mockFetch.mockResolvedValue(makeWalResponse('EURUSD'))
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useWalTimeline('EURUSD'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.events).toHaveLength(3)
    expect(result.current.data?.asset).toBe('EURUSD')
  })

  it('does not fetch when asset name is empty', () => {
    const { wrapper } = withQueryClient()
    renderHook(() => useWalTimeline(''), { wrapper })
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('handles schema validation failure gracefully', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    mockFetch.mockResolvedValue({ invalid: true })
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useWalTimeline('EURUSD'), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(consoleSpy).toHaveBeenCalledWith('[WAL] validation failed:', expect.any(Array))
    expect(result.current.data?.events).toEqual([])
    consoleSpy.mockRestore()
  })

  it('enters error state on network failure', async () => {
    mockFetch.mockRejectedValue(new Error('Network error'))
    const { wrapper } = withQueryClient()
    const { result } = renderHook(() => useWalTimeline('EURUSD'), { wrapper })
    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})

describe('groupWalEvents', () => {
  it('groups events by feature_hash and sorts by sequence', () => {
    const events: WalEvent[] = [
      { sequence: 1, timestamp: '2026-07-05T00:00:01Z', event_type: 'features_snapshot', payload: { feature_hash: 'abc' } },
      { sequence: 3, timestamp: '2026-07-05T00:00:03Z', event_type: 'inference_output', payload: { feature_hash: 'abc' } },
      { sequence: 2, timestamp: '2026-07-05T00:00:02Z', event_type: 'features_snapshot', payload: { feature_hash: 'abc' } },
    ]
    const groups = groupWalEvents(events)
    expect(groups).toHaveLength(1)
    expect(groups[0].featureHash).toBe('abc')
    expect(groups[0].events.map(e => e.sequence)).toEqual([1, 2, 3])
  })

  it('skips events without feature_hash', () => {
    const events: WalEvent[] = [
      { sequence: 1, timestamp: '', event_type: 'features_snapshot', payload: { feature_hash: 'abc' } },
      { sequence: 2, timestamp: '', event_type: 'features_snapshot', payload: {} },
    ]
    const groups = groupWalEvents(events)
    expect(groups).toHaveLength(1)
  })

  it('returns groups sorted by sequence descending', () => {
    const events: WalEvent[] = [
      { sequence: 10, timestamp: '', event_type: 'features_snapshot', payload: { feature_hash: 'older' } },
      { sequence: 20, timestamp: '', event_type: 'features_snapshot', payload: { feature_hash: 'newer' } },
    ]
    const groups = groupWalEvents(events)
    expect(groups).toHaveLength(2)
    expect(groups[0].featureHash).toBe('newer')
    expect(groups[1].featureHash).toBe('older')
  })
})
