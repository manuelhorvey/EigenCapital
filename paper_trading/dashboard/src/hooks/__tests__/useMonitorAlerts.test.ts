import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useMonitorAlerts, setDismissedVersion } from '../useMonitorAlerts'

const bundleState: { current: unknown } = { current: { data: undefined } }

// Mock useSystemSnapshot to apply selectors (like the real one does via React Query's select)
vi.mock('../useSystemSnapshot', () => ({
  useSystemSnapshot: (select?: (data: unknown) => unknown) => {
    const current = bundleState.current as { data: unknown } | undefined
    if (!current || current.data === undefined) {
      return { data: undefined, isPending: true, isLoading: true }
    }
    return {
      data: select ? select(current.data) : current.data,
      isPending: false,
      isLoading: false,
    }
  },
}))

// Use a shared reference so the test can inspect the channel's spies
let broadcastInstances: Array<{
  close: ReturnType<typeof vi.fn>
  addEventListener: ReturnType<typeof vi.fn>
  removeEventListener: ReturnType<typeof vi.fn>
  postMessage: ReturnType<typeof vi.fn>
  dispatchEvent: ReturnType<typeof vi.fn>
  name: string
}> = []

class MockBroadcastChannel {
  close = vi.fn()
  addEventListener = vi.fn()
  removeEventListener = vi.fn()
  postMessage = vi.fn()
  dispatchEvent = vi.fn()
  name: string
  onmessage: unknown = null
  onmessageerror: unknown = null

  constructor(name: string) {
    this.name = name
    broadcastInstances.push({
      close: this.close,
      addEventListener: this.addEventListener,
      removeEventListener: this.removeEventListener,
      postMessage: this.postMessage,
      dispatchEvent: this.dispatchEvent,
      name: this.name,
    })
  }
}

describe('useMonitorAlerts', () => {
  beforeEach(() => {
    broadcastInstances = []
    vi.stubGlobal('BroadcastChannel', MockBroadcastChannel)
    sessionStorage.clear()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    // Reset dismissed version between tests so the previous test's
    // synchronous version-ref update doesn't leak into the next test.
    setDismissedVersion('')
  })

  it('returns empty array when bundle is undefined', () => {
    const { unmount, result } = renderHook(() => useMonitorAlerts())
    expect(result.current).toEqual([])
    unmount() // Clean up singleton so next test gets a fresh channel
  })

  it('calls close on the BroadcastChannel when unmounted', async () => {
    const { unmount } = renderHook(() => useMonitorAlerts())

    // Wait for the effect to set up the channel
    await waitFor(() => {
      expect(broadcastInstances.length).toBeGreaterThanOrEqual(1)
    })

    const channel = broadcastInstances[0]

    expect(channel.addEventListener).toHaveBeenCalled()
    expect(channel.close).not.toHaveBeenCalled()

    unmount()

    await waitFor(() => {
      expect(channel.removeEventListener).toHaveBeenCalled()
      expect(channel.close).toHaveBeenCalledOnce()
    })
  })

  it('re-creates channel on remount after unmount', async () => {
    // First mount
    const { unmount } = renderHook(() => useMonitorAlerts())

    await waitFor(() => {
      expect(broadcastInstances.length).toBe(1)
    })
    const firstChannel = broadcastInstances[0]
    expect(firstChannel.addEventListener).toHaveBeenCalled()

    unmount()

    await waitFor(() => {
      expect(firstChannel.close).toHaveBeenCalledOnce()
    })

    // Reset the tracked instances so we can detect the new channel
    broadcastInstances = []

    // Second mount
    renderHook(() => useMonitorAlerts())

    await waitFor(() => {
      expect(broadcastInstances.length).toBe(1)
    })
    const secondChannel = broadcastInstances[0]
    expect(secondChannel.addEventListener).toHaveBeenCalled()
    expect(secondChannel.close).not.toHaveBeenCalled()
    // The test asserts that a NEW channel instance (not the old one)
    // has addEventListener called — proving re-creation worked
  })
})

// ── B2: dismissal state migration bug ──────────────────────────────
//
// The dashboard persists dismissed alerts to sessionStorage keyed by
// the dashboard contract version. The prior implementation deferred the
// version-key update to a useEffect, so the first render's lookup key
// was always the unversioned 'ec-dismissed-alerts'. As soon as the bundle
// arrived, the lookup key rotated to the versioned form — silently
// invalidating every prior dismissal.
//
// These tests pin down the synchronous-key behavior.

function setBundle(version: string, haltedAssets: string[]) {
  const assets = Object.fromEntries(
    haltedAssets.map(name => [
      name,
      {
        halt: { halted: true, reasons: ['test reason'] },
        metrics: {},
      },
    ])
  )
  bundleState.current = {
    data: {
      meta: {
        version,
        server_time: '2026-07-04T12:00:00Z',
        snapshot_time: '2026-07-04T12:00:00Z',
        snapshot_sequence_id: 1,
        status: 'ok',
      },
      snapshot: {
        timestamp: '2026-07-04T12:00:00Z',
        assets,
        halt_conditions: { drawdown: 0, prob_drift: 0 },
      },
      live: { health: null, mt5: null },
    },
  }
}

describe('useMonitorAlerts — dismissal migration (B2)', () => {
  beforeEach(() => {
    sessionStorage.clear()
    bundleState.current = { data: undefined }
    broadcastInstances = []
    vi.stubGlobal('BroadcastChannel', MockBroadcastChannel)
    setDismissedVersion('')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('uses the versioned key on the FIRST render with non-empty version', async () => {
    // Pre-seed an alert as "dismissed" under the versioned key (the form
    // recorded by another tab or a previous session).
    const persistedKey = 'ec-dismissed-alerts-v1.0.0'
    sessionStorage.setItem(persistedKey, JSON.stringify(['halt-test-reason']))

    setBundle('v1.0.0', ['EURUSD'])

    const { result, unmount } = renderHook(() => useMonitorAlerts())

    await waitFor(() => {
      // First render with a halted asset should NOT surface a EURUSD
      // alert because the prior dismissal at the versioned key applies.
      expect(result.current.length).toBe(0)
    })
    unmount()
  })

  it('does not expose a window where the unversioned key reads old', async () => {
    // The pre-bug version would look up unversioned key first (returning
    // []) and then the versioned key on the second render, exposing
    // dismissed alerts incorrectly across the migration.
    const persistedUnversioned = 'ec-dismissed-alerts'
    sessionStorage.setItem(persistedUnversioned, JSON.stringify(['halt-test-reason']))

    setBundle('v2.0.0', ['EURUSD'])

    const { result, unmount } = renderHook(() => useMonitorAlerts())

    await waitFor(() => {
      // The EURUSD halted alert appears (correct), because the prior
      // dismissal was unversioned (legacy) and the new version starts
      // fresh. The bug B2 fix must NOT mistakenly read the unversioned
      // key on the versioned render.
      expect(result.current.some((a: { asset: string }) => a.asset === 'EURUSD')).toBe(true)
    })
    unmount()
  })
})
