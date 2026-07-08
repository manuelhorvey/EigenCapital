import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useSnapshotReconciler } from '../useSnapshotReconciler'
import { QUERY_KEYS } from '../../lib/queryKeys'
import type { SystemBundle } from '../../types/bundle'

function makeBundle(seqId: number, contractVersion: number | null = 2): SystemBundle {
  return {
    meta: {
      version: 'v1',
      server_time: '2026-07-04T00:00:00Z',
      snapshot_time: '2026-07-04T00:00:00Z',
      snapshot_sequence_id: seqId,
      status: 'ok',
      max_live_age_seconds: 30,
      request_id: 'test-request-id',
    },
    snapshot: {
      contract_version: contractVersion ?? undefined,
      sequence_id: seqId,
      schema_version: '1.0.0',
      timestamp: '2026-07-04T00:00:00Z',
      assets: {},
      portfolio: {},
      open_positions: {},
      engine_status: { initialized: true },
      halt_conditions: { drawdown: 0, prob_drift: 0 },
    } as never,
    live: {
      health: {
        fetch_time: '2026-07-04T00:00:00Z',
        engine_alive: true,
        engine_status: 'ACTIVE',
        requested_at: '2026-07-04T00:00:00Z',
      },
      mt5: {
        fetch_time: '2026-07-04T00:00:00Z',
        connected: false,
        status: 'UNKNOWN',
      },
    },
  } as unknown as SystemBundle
}

function withQueryClient(_bundle: SystemBundle | undefined) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  // Pre-seed invalidation spy
  const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
  const setDataSpy = vi.spyOn(queryClient, 'setQueryData')

  // Wrap renderHook with provider
  function wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
  }

  // Pre-populate cache with a sentinel so reconcile writes can be inspected
  queryClient.setQueryData(QUERY_KEYS.system, { __seed__: true })

  return { wrapper, invalidateSpy, setDataSpy, queryClient }
}

describe('useSnapshotReconciler', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('first mount records baseline without invalidating', () => {
    const { wrapper, invalidateSpy } = withQueryClient(makeBundle(5))
    const { rerender } = renderHook((props: SystemBundle | undefined) => useSnapshotReconciler(props), {
      wrapper,
      initialProps: makeBundle(5),
    })
    expect(invalidateSpy).not.toHaveBeenCalled()
    rerender(makeBundle(5))
    expect(invalidateSpy).not.toHaveBeenCalled()
  })

  it('forward seq increment does NOT trigger reconcile', () => {
    const { wrapper, invalidateSpy } = withQueryClient(makeBundle(5))
    const { rerender } = renderHook((props: SystemBundle | undefined) => useSnapshotReconciler(props), {
      wrapper,
      initialProps: makeBundle(5),
    })
    rerender(makeBundle(6))
    expect(invalidateSpy).not.toHaveBeenCalled()
    rerender(makeBundle(7))
    expect(invalidateSpy).not.toHaveBeenCalled()
  })

  it('backward step (seqId dropped) DOES trigger reconcile', () => {
    const { wrapper, invalidateSpy } = withQueryClient(makeBundle(5))
    const { rerender } = renderHook((props: SystemBundle | undefined) => useSnapshotReconciler(props), {
      wrapper,
      initialProps: makeBundle(5),
    })
    rerender(makeBundle(2))
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: QUERY_KEYS.system })
  })

  it('cold start (seqId 0 after restart from higher value) reconciles', () => {
    const { wrapper, invalidateSpy } = withQueryClient(makeBundle(500))
    const { rerender } = renderHook((props: SystemBundle | undefined) => useSnapshotReconciler(props), {
      wrapper,
      initialProps: makeBundle(500),
    })
    rerender(makeBundle(0))
    expect(invalidateSpy).toHaveBeenCalled()
  })

  it('suspicious forward jump > 3 reconciliates (conservative guard)', () => {
    const { wrapper, invalidateSpy } = withQueryClient(makeBundle(1))
    const { rerender } = renderHook((props: SystemBundle | undefined) => useSnapshotReconciler(props), {
      wrapper,
      initialProps: makeBundle(1),
    })
    rerender(makeBundle(7))
    expect(invalidateSpy).toHaveBeenCalled()
  })

  it('contract version mismatch triggers reconcile', () => {
    const { wrapper, invalidateSpy } = withQueryClient(makeBundle(1, 2))
    const { rerender } = renderHook((props: SystemBundle | undefined) => useSnapshotReconciler(props), {
      wrapper,
      initialProps: makeBundle(1, 2),
    })
    rerender(makeBundle(2, 3))
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: QUERY_KEYS.system })
  })

  it('null seqId leaves state untouched (engine not yet running)', () => {
    const { wrapper, invalidateSpy } = withQueryClient(undefined)
    const { rerender } = renderHook((props: SystemBundle | undefined) => useSnapshotReconciler(props), {
      wrapper,
      initialProps: undefined,
    })
    rerender(makeBundle(5))
    expect(invalidateSpy).not.toHaveBeenCalled()
  })

  it('reconcile writes the bundle to cache before invalidating', () => {
    const bundle = makeBundle(5)
    const { wrapper, invalidateSpy, setDataSpy } = withQueryClient(bundle)
    const { rerender } = renderHook((props: SystemBundle | undefined) => useSnapshotReconciler(props), {
      wrapper,
      initialProps: bundle,
    })
    const newBundle = makeBundle(2)
    rerender(newBundle)
    // setQueryData writes first, then invalidate
    expect(setDataSpy).toHaveBeenCalledWith(QUERY_KEYS.system, newBundle)
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: QUERY_KEYS.system })
  })
})
