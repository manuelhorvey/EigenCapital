import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useMonitorAlerts } from '../useMonitorAlerts'

// Mock useSystemSnapshot
vi.mock('../useSystemSnapshot', () => ({
  useSystemSnapshot: () => ({ data: undefined }),
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
