import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useBrowserNotifications, notifTag } from '../useBrowserNotifications'

// ── Mock Notification API ─────────────────────────────────────────

interface CapturedNotification {
  title: string
  options: NotificationOptions
  addEventListener: ReturnType<typeof vi.fn>
  close: ReturnType<typeof vi.fn>
}

const fakeNotificationInstances: CapturedNotification[] = []

let mockPermission: NotificationPermission = 'default'
let mockRequestPermission: () => Promise<NotificationPermission> = () =>
  Promise.resolve('default' as NotificationPermission)

function resetMocks() {
  fakeNotificationInstances.length = 0
  mockPermission = 'default'
  mockRequestPermission = () => Promise.resolve('default' as NotificationPermission)
  localStorage.clear()
}

/**
 * Replaces `globalThis.Notification` with a fake constructor that
 * captures arguments into `fakeNotificationInstances` and supports
 * `.permission` (getter) and `.requestPermission()`.
 */
function stubNotification(permission: NotificationPermission) {
  mockPermission = permission

  class FakeNotification {
    title: string
    options: NotificationOptions
    static permission: NotificationPermission = permission
    static requestPermission: () => Promise<NotificationPermission> = mockRequestPermission
    addEventListener = vi.fn()
    close = vi.fn()

    constructor(title: string, options?: NotificationOptions) {
      this.title = title
      this.options = options ?? {}
      fakeNotificationInstances.push({
        title: this.title,
        options: this.options,
        addEventListener: this.addEventListener,
        close: this.close,
      })
    }
  }

  vi.stubGlobal('Notification', FakeNotification)
}

/**
 * Installs a Notification stub that works for the general case but
 * removes `permission` from the prototype so `'permission' in Notification`
 * remains true for the `supported` check while `.permission` reads the
 * static property correctly.
 */
function stubNotificationWithStaticPermission(permission: NotificationPermission) {
  mockPermission = permission

  class FakeNotification {
    title: string
    options: NotificationOptions
    static permission: NotificationPermission = permission
    static requestPermission: () => Promise<NotificationPermission> = mockRequestPermission
    addEventListener = vi.fn()
    close = vi.fn()

    constructor(title: string, options?: NotificationOptions) {
      this.title = title
      this.options = options ?? {}
      fakeNotificationInstances.push({
        title: this.title,
        options: this.options,
        addEventListener: this.addEventListener,
        close: this.close,
      })
    }
  }

  vi.stubGlobal('Notification', FakeNotification as unknown as NotificationConstructor)
}

// ── Tests ─────────────────────────────────────────────────────────

describe('useBrowserNotifications', () => {
  beforeEach(() => {
    resetMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  // ── Supported / SSR ─────────────────────────────────────────────

  describe('supported / SSR', () => {
    it('returns supported=true when Notification API exists with granted permission', () => {
      stubNotification('granted')
      const { result } = renderHook(() => useBrowserNotifications())
      expect(result.current.supported).toBe(true)
      expect(result.current.permission).toBe('granted')
    })

    it('returns supported=true with denied permission', () => {
      stubNotification('denied')
      const { result } = renderHook(() => useBrowserNotifications())
      expect(result.current.supported).toBe(true)
      expect(result.current.permission).toBe('denied')
    })

    it('returns supported=true with default permission', () => {
      stubNotification('default')
      const { result } = renderHook(() => useBrowserNotifications())
      expect(result.current.supported).toBe(true)
      expect(result.current.permission).toBe('default')
    })

    it('returns supported=false when Notification is not in window', () => {
      // Remove Notification from global scope entirely so
      // `'Notification' in window` evaluates to false
      const origDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'Notification')
      try {
        // Delete Notification from globalThis
        delete (globalThis as Record<string, unknown>).Notification
        const { result } = renderHook(() => useBrowserNotifications())
        expect(result.current.supported).toBe(false)
        expect(result.current.permission).toBe('denied')
      } finally {
        // Restore
        if (origDescriptor) {
          Object.defineProperty(globalThis, 'Notification', origDescriptor)
        }
      }
    })
  })

  // ── Initial enabled state ───────────────────────────────────────

  describe('enabled state', () => {
    it('defaults to true when localStorage is not set', () => {
      stubNotification('granted')
      localStorage.removeItem('ec-desktop-notifications')
      const { result } = renderHook(() => useBrowserNotifications())
      expect(result.current.enabled).toBe(true)
    })

    it('reads true from localStorage', () => {
      localStorage.setItem('ec-desktop-notifications', 'true')
      stubNotification('granted')
      const { result } = renderHook(() => useBrowserNotifications())
      expect(result.current.enabled).toBe(true)
    })

    it('reads false from localStorage', () => {
      localStorage.setItem('ec-desktop-notifications', 'false')
      stubNotification('granted')
      const { result } = renderHook(() => useBrowserNotifications())
      expect(result.current.enabled).toBe(false)
    })

    it('parses non-true localStorage values as disabled', () => {
      localStorage.setItem('ec-desktop-notifications', 'garbage')
      stubNotification('granted')
      const { result } = renderHook(() => useBrowserNotifications())
      // 'garbage' !== null → stored is truthy → 'garbage' === 'true' → false
      expect(result.current.enabled).toBe(false)
    })
  })

  // ── setEnabled ──────────────────────────────────────────────────

  describe('setEnabled', () => {
    it('sets enabled to true and persists to localStorage', () => {
      localStorage.setItem('ec-desktop-notifications', 'false')
      stubNotification('granted')
      const { result } = renderHook(() => useBrowserNotifications())
      expect(result.current.enabled).toBe(false)

      act(() => { result.current.setEnabled(true) })
      expect(result.current.enabled).toBe(true)
      expect(localStorage.getItem('ec-desktop-notifications')).toBe('true')
    })

    it('sets enabled to false and persists to localStorage', () => {
      localStorage.setItem('ec-desktop-notifications', 'true')
      stubNotification('granted')
      const { result } = renderHook(() => useBrowserNotifications())
      expect(result.current.enabled).toBe(true)

      act(() => { result.current.setEnabled(false) })
      expect(result.current.enabled).toBe(false)
      expect(localStorage.getItem('ec-desktop-notifications')).toBe('false')
    })

    it('toggles correctly back and forth', () => {
      stubNotification('granted')
      const { result } = renderHook(() => useBrowserNotifications())

      act(() => { result.current.setEnabled(false) })
      expect(localStorage.getItem('ec-desktop-notifications')).toBe('false')

      act(() => { result.current.setEnabled(true) })
      expect(localStorage.getItem('ec-desktop-notifications')).toBe('true')
    })
  })

  // ── requestPermission ───────────────────────────────────────────

  describe('requestPermission', () => {
    it('calls Notification.requestPermission and updates state on resolve', async () => {
      let resolve!: (p: NotificationPermission) => void
      mockRequestPermission = () => new Promise(r => { resolve = r })
      stubNotification('default')
      const { result } = renderHook(() => useBrowserNotifications())

      let returned: NotificationPermission | undefined
      act(() => {
        result.current.requestPermission().then(r => { returned = r })
      })
      await act(async () => {
        resolve('granted')
        mockPermission = 'granted'
        await Promise.resolve()
      })

      expect(result.current.permission).toBe('granted')
      expect(returned).toBe('granted')
    })

    it('returns "denied" when requestPermission rejects', async () => {
      mockRequestPermission = () => Promise.reject(new Error('blocked'))
      stubNotification('default')
      const { result } = renderHook(() => useBrowserNotifications())

      let returned: NotificationPermission | undefined
      act(() => {
        result.current.requestPermission().then(r => { returned = r })
      })
      await act(async () => {
        await Promise.resolve() // flush microtasks
      })

      expect(returned).toBe('denied')
    })
  })

  // ── notify ──────────────────────────────────────────────────────

  describe('notify', () => {
    it('creates a Notification with the given title', () => {
      stubNotification('granted')
      const { result } = renderHook(() => useBrowserNotifications())

      act(() => { result.current.notify({ title: 'Test alert' }) })
      expect(fakeNotificationInstances).toHaveLength(1)
      expect(fakeNotificationInstances[0].title).toBe('Test alert')
    })

    it('passes body, icon, and tag to the Notification constructor', () => {
      stubNotification('granted')
      const { result } = renderHook(() => useBrowserNotifications())

      act(() => {
        result.current.notify({
          title: 'Alert',
          body: 'Something happened',
          icon: '/custom-icon.png',
          tag: 'my-tag',
        })
      })

      const n = fakeNotificationInstances[0]
      expect(n.options.body).toBe('Something happened')
      expect(n.options.icon).toBe('/custom-icon.png')
      expect(n.options.tag).toBe('my-tag')
    })

    it('defaults icon to /favicon.ico', () => {
      stubNotification('granted')
      const { result } = renderHook(() => useBrowserNotifications())

      act(() => { result.current.notify({ title: 'Default icon' }) })
      expect(fakeNotificationInstances[0].options.icon).toBe('/favicon.ico')
    })

    it('auto-generates tag from title when tag is omitted', () => {
      stubNotification('granted')
      const { result } = renderHook(() => useBrowserNotifications())

      act(() => { result.current.notify({ title: 'Auto tag' }) })
      expect(fakeNotificationInstances[0].options.tag).toBe('ec-notif-Auto tag')
    })

    it('is a no-op when supported is false', () => {
      // Simulate Notification not being in window (SSR / unsupported browser)
      const origDesc = Object.getOwnPropertyDescriptor(globalThis, 'Notification')
      try {
        delete (globalThis as Record<string, unknown>).Notification
        const { result } = renderHook(() => useBrowserNotifications())

        act(() => { result.current.notify({ title: 'Should skip' }) })
        expect(fakeNotificationInstances).toHaveLength(0)
      } finally {
        if (origDesc) Object.defineProperty(globalThis, 'Notification', origDesc)
      }
    })

    it('is a no-op when permission is default', () => {
      stubNotification('default')
      const { result } = renderHook(() => useBrowserNotifications())

      act(() => { result.current.notify({ title: 'Default permission' }) })
      expect(fakeNotificationInstances).toHaveLength(0)
    })

    it('is a no-op when permission is denied', () => {
      stubNotification('denied')
      const { result } = renderHook(() => useBrowserNotifications())

      act(() => { result.current.notify({ title: 'Denied' }) })
      expect(fakeNotificationInstances).toHaveLength(0)
    })

    it('skips when enabled is false and force is not set', () => {
      localStorage.setItem('ec-desktop-notifications', 'false')
      stubNotification('granted')
      const { result } = renderHook(() => useBrowserNotifications())

      act(() => { result.current.notify({ title: 'Opted out' }) })
      expect(fakeNotificationInstances).toHaveLength(0)
    })

    it('fires when enabled is false but force is true', () => {
      localStorage.setItem('ec-desktop-notifications', 'false')
      stubNotification('granted')
      const { result } = renderHook(() => useBrowserNotifications())

      act(() => { result.current.notify({ title: 'Force fire', force: true }) })
      expect(fakeNotificationInstances).toHaveLength(1)
      expect(fakeNotificationInstances[0].title).toBe('Force fire')
    })

    it('handles Notification constructor throwing gracefully', () => {
      // Make constructor throw
      class ThrowingNotification {
        static permission: NotificationPermission = 'granted'
        static requestPermission = () => Promise.resolve('granted' as NotificationPermission)
        constructor() { throw new Error('constructor failed') }
      }
      vi.stubGlobal('Notification', ThrowingNotification as unknown as NotificationConstructor)

      const { result } = renderHook(() => useBrowserNotifications())

      expect(() => {
        act(() => { result.current.notify({ title: 'Will throw' }) })
      }).not.toThrow()
    })

    // ── onClickUrl ──────────────────────────────────────────────

    describe('onClickUrl', () => {
      let focusSpy: ReturnType<typeof vi.spyOn>

      beforeEach(() => {
        focusSpy = vi.spyOn(window, 'focus').mockImplementation(() => {})
      })

      afterEach(() => {
        focusSpy.mockRestore()
      })

      it('registers a click event listener when onClickUrl is provided', () => {
        stubNotificationWithStaticPermission('granted')
        const { result } = renderHook(() => useBrowserNotifications())

        act(() => {
          result.current.notify({ title: 'Click test', onClickUrl: '/some-url' })
        })

        expect(fakeNotificationInstances).toHaveLength(1)
        const notif = fakeNotificationInstances[0]
        expect(notif.addEventListener).toHaveBeenCalledWith('click', expect.any(Function))
      })

      it('click handler focuses the window', () => {
        stubNotificationWithStaticPermission('granted')
        const { result } = renderHook(() => useBrowserNotifications())

        act(() => {
          result.current.notify({ title: 'Focus test', onClickUrl: '/other' })
        })

        const notif = fakeNotificationInstances[0]
        const handler = notif.addEventListener.mock.calls[0][1] as () => void
        expect(handler).toBeInstanceOf(Function)

        handler()
        expect(focusSpy).toHaveBeenCalledOnce()
      })

      it('navigates to the onClickUrl when different from current location', () => {
        let currentHref = '/current'
        const mockLocation = {
          ...window.location,
          get href() { return currentHref },
          set href(v: string | undefined) { currentHref = v ?? '' },
        }
        const locSpy = vi.spyOn(window, 'location', 'get').mockReturnValue(mockLocation)

        stubNotificationWithStaticPermission('granted')
        const { result } = renderHook(() => useBrowserNotifications())

        act(() => {
          result.current.notify({ title: 'Nav test', onClickUrl: '/target' })
        })

        const notif = fakeNotificationInstances[0]
        const handler = notif.addEventListener.mock.calls[0][1] as () => void

        handler()
        expect(currentHref).toBe('/target')

        locSpy.mockRestore()
      })

      it('does not navigate when onClickUrl matches current location', () => {
        const initialHref = '/same'
        let currentHref = initialHref
        const mockLocation = {
          ...window.location,
          get href() { return currentHref },
          set href(v: string | undefined) { currentHref = v ?? '' },
        }
        const locSpy = vi.spyOn(window, 'location', 'get').mockReturnValue(mockLocation)

        stubNotificationWithStaticPermission('granted')
        const { result } = renderHook(() => useBrowserNotifications())

        act(() => {
          result.current.notify({ title: 'Same URL', onClickUrl: '/same' })
        })

        const notif = fakeNotificationInstances[0]
        const handler = notif.addEventListener.mock.calls[0][1] as () => void

        handler()
        expect(currentHref).toBe('/same')

        locSpy.mockRestore()
      })

      it('does not register a click listener when onClickUrl is omitted', () => {
        stubNotificationWithStaticPermission('granted')
        const { result } = renderHook(() => useBrowserNotifications())

        act(() => {
          result.current.notify({ title: 'No URL' })
        })

        const notif = fakeNotificationInstances[0]
        expect(notif.addEventListener).not.toHaveBeenCalled()
      })

      it('calls close() after the click handler runs', () => {
        let currentHref = '/a'
        const mockLocation = {
          ...window.location,
          get href() { return currentHref },
          set href(v: string | undefined) { currentHref = v ?? '' },
        }
        const locSpy = vi.spyOn(window, 'location', 'get').mockReturnValue(mockLocation)

        stubNotificationWithStaticPermission('granted')
        const { result } = renderHook(() => useBrowserNotifications())

        act(() => {
          result.current.notify({ title: 'Close test', onClickUrl: '/b' })
        })

        const notif = fakeNotificationInstances[0]
        const handler = notif.addEventListener.mock.calls[0][1] as () => void

        handler()
        expect(notif.close).toHaveBeenCalledOnce()

        locSpy.mockRestore()
      })
    })
  })

  // ── navigator.permissions sync ─────────────────────────────────

  describe('permission sync', () => {
    it('queries navigator.permissions and syncs on initial mount', () => {
      stubNotification('granted')
      const querySpy = vi.fn().mockResolvedValue({ onchange: null })
      vi.stubGlobal('navigator', {
        ...navigator,
        permissions: { query: querySpy },
      })

      renderHook(() => useBrowserNotifications())

      expect(querySpy).toHaveBeenCalledWith({ name: 'notifications' })
    })

    it('fires status.onchange when external permission changes', async () => {
      stubNotification('default')

      // Capture the status object so the test can fire its onchange handler
      let status: { onchange: (() => void) | null } = { onchange: null }
      const querySpy = vi.fn().mockResolvedValue(status)
      vi.stubGlobal('navigator', {
        ...navigator,
        permissions: { query: querySpy },
      })

      const { result } = renderHook(() => useBrowserNotifications())

      // Wait for the query promise to resolve and onchange to be assigned
      await vi.waitFor(() => {
        expect(typeof status.onchange).toBe('function')
      })

      // Initial permission is 'default' (from stubNotification('default'))
      expect(result.current.permission).toBe('default')

      // Simulate the user changing site permission in browser settings
      // Update the global Notification.permission
      const FakeNotif = globalThis.Notification as unknown as {
        permission: NotificationPermission
      }
      FakeNotif.permission = 'granted'

      // Fire the onchange callback — the sync function reads Notification.permission
      act(() => {
        status.onchange!()
      })

      expect(result.current.permission).toBe('granted')
    })

    it('cancelled effect does not fire onchange after unmount', async () => {
      stubNotification('default')

      let status: { onchange: (() => void) | null } = { onchange: null }
      const querySpy = vi.fn().mockResolvedValue(status)
      vi.stubGlobal('navigator', {
        ...navigator,
        permissions: { query: querySpy },
      })

      const { result, unmount } = renderHook(() => useBrowserNotifications())

      await vi.waitFor(() => {
        expect(typeof status.onchange).toBe('function')
      })

      // Unmount — sets cancelled = true
      unmount()

      // Change permission and fire onchange
      const FakeNotif = globalThis.Notification as unknown as {
        permission: NotificationPermission
      }
      FakeNotif.permission = 'granted'
      status.onchange!()

      // Permission should still be 'default' because cancelled blocked the sync
      expect(result.current.permission).toBe('default')
    })

    it('handles navigator.permissions being undefined gracefully', () => {
      stubNotification('granted')
      // Remove permissions API
      vi.stubGlobal('navigator', {
        ...navigator,
        permissions: undefined,
      })

      // Should not throw
      expect(() => {
        renderHook(() => useBrowserNotifications())
      }).not.toThrow()
    })
  })

  // ── notifTag ────────────────────────────────────────────────────

  describe('notifTag', () => {
    it('returns tag with ec-notif- prefix', () => {
      expect(notifTag('engine-lost')).toBe('ec-notif-engine-lost')
      expect(notifTag('rejection-AUDUSD')).toBe('ec-notif-rejection-AUDUSD')
    })
  })

  // ── Return shape ────────────────────────────────────────────────

  it('returns all expected properties and functions', () => {
    stubNotification('granted')
    const { result } = renderHook(() => useBrowserNotifications())

    expect(result.current).toHaveProperty('supported')
    expect(result.current).toHaveProperty('permission')
    expect(result.current).toHaveProperty('enabled')
    expect(result.current).toHaveProperty('setEnabled')
    expect(result.current).toHaveProperty('requestPermission')
    expect(result.current).toHaveProperty('notify')
    expect(typeof result.current.setEnabled).toBe('function')
    expect(typeof result.current.requestPermission).toBe('function')
    expect(typeof result.current.notify).toBe('function')
  })
})
