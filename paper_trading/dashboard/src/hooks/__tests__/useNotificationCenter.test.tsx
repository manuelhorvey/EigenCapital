import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, renderHook } from '@testing-library/react'
import { NotificationProvider, useNotificationCenter } from '../useNotificationCenter'
import type { Notification } from '../useNotificationCenter'

// ── Helper ────────────────────────────────────────────────────────

/**
 * Renders a NotificationProvider and returns the hook's API.
 *
 * All state reads (`notifications`, `unreadCount`) are **lazy getters**
 * so they always reflect the latest value after `act(...)` settles.
 */
function setup() {
  let api!: ReturnType<typeof useNotificationCenter>

  function Trigger() {
    api = useNotificationCenter()
    return null
  }

  render(
    <NotificationProvider>
      <Trigger />
    </NotificationProvider>,
  )

  /** Lazy getter – always reads the live array. */
  function getNotifications(): Notification[] {
    return api.notifications
  }

  /** Lazy getter – always reads the live count. */
  function getUnreadCount(): number {
    return api.unreadCount
  }

  return {
    add: (opts: Parameters<typeof api.add>[0]) => api.add(opts),
    markRead: (id: string) => api.markRead(id),
    markAllRead: () => api.markAllRead(),
    clear: () => api.clear(),
    getNotifications,
    getUnreadCount,
    /** Convenience: number of notifications */
    notificationsCount: () => api.notifications.length,
    /** Convenience: is every notification read? */
    allRead: () => api.notifications.every(n => n.read),
    /** Convenience: find a notification by id */
    find: (id: string) => api.notifications.find(n => n.id === id),
    /** Convenience: first notification (only use when you know there is one) */
    first: () => api.notifications[0],
  }
}

/** Render a bare hook outside a provider to test the error path. */
function renderOutsideProvider() {
  return renderHook(() => useNotificationCenter())
}

// ── Tests ─────────────────────────────────────────────────────────

describe('useNotificationCenter', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // ── Add ─────────────────────────────────────────────────────────

  it('adds a notification and returns its id', () => {
    const { add, getNotifications, notificationsCount } = setup()

    let id: string
    act(() => {
      id = add({ title: 'Test notification', type: 'info' })
    })

    expect(id).toBeDefined()
    expect(id).toMatch(/^notif-/)
    expect(notificationsCount()).toBe(1)

    const n = getNotifications()[0]
    expect(n.title).toBe('Test notification')
    expect(n.type).toBe('info')
    expect(n.read).toBe(false)
    expect(n.timestamp).toBeGreaterThan(0)
  })

  it('adds a notification with explicit fields', () => {
    const { add, getNotifications } = setup()
    const fixedTs = 1_700_000_000_000

    act(() => {
      vi.setSystemTime(fixedTs)
      add({
        id: 'custom-id',
        type: 'error',
        title: 'Critical error',
        message: 'Something went wrong',
      })
    })

    expect(getNotifications()).toHaveLength(1)
    expect(getNotifications()[0]).toMatchObject({
      id: 'custom-id',
      type: 'error',
      title: 'Critical error',
      message: 'Something went wrong',
      read: false,
    })
    expect(getNotifications()[0].timestamp).toBe(fixedTs)
  })

  it('defaults type to info when not provided', () => {
    const { add, first } = setup()

    act(() => {
      add({ title: 'Default type' })
    })

    expect(first().type).toBe('info')
  })

  it('generates unique ids even for rapid successive calls', () => {
    const { add } = setup()

    let id1: string
    let id2: string
    act(() => {
      id1 = add({ title: 'A' })
      id2 = add({ title: 'B' })
      expect(id1).not.toBe(id2)
    })
  })

  // ── Dedup ───────────────────────────────────────────────────────

  it('does not add a notification with a duplicate id', () => {
    const { add, getNotifications } = setup()

    act(() => {
      add({ id: 'dup', title: 'First' })
      add({ id: 'dup', title: 'Second' })
    })

    expect(getNotifications()).toHaveLength(1)
    expect(getNotifications()[0].title).toBe('First')
  })

  // ── Max history ─────────────────────────────────────────────────

  it('caps at MAX_HISTORY (200) notifications', () => {
    const { add, getNotifications } = setup()

    act(() => {
      for (let i = 0; i < 210; i++) {
        add({ id: `n-${i}`, title: `Notification ${i}` })
      }
    })

    expect(getNotifications()).toHaveLength(200)
    // The oldest 10 are evicted; the newest 200 remain
    expect(getNotifications()[0].id).toBe('n-10')
    expect(getNotifications()[199].id).toBe('n-209')
  })

  // ── markRead ────────────────────────────────────────────────────

  it('marks a single notification as read', () => {
    const { add, markRead, find } = setup()

    let id: string
    act(() => {
      id = add({ title: 'Unread' })
    })
    expect(find(id)!.read).toBe(false)

    act(() => {
      markRead(id)
    })
    expect(find(id)!.read).toBe(true)
  })

  it('is a no-op when marking a non-existent id', () => {
    const { add, markRead, getNotifications } = setup()

    act(() => {
      add({ id: 'a', title: 'A' })
      add({ id: 'b', title: 'B' })
    })
    expect(getNotifications()).toHaveLength(2)

    act(() => {
      markRead('non-existent')
    })
    expect(getNotifications()).toHaveLength(2)
    expect(getNotifications().every(n => !n.read)).toBe(true)
  })

  it('only marks the targeted notification as read', () => {
    const { add, markRead, find } = setup()

    let id1: string
    let id2: string
    act(() => {
      id1 = add({ title: 'First' })
      id2 = add({ title: 'Second' })
    })

    act(() => {
      markRead(id1)
    })

    expect(find(id1)!.read).toBe(true)
    expect(find(id2)!.read).toBe(false)
  })

  // ── markAllRead ─────────────────────────────────────────────────

  it('marks all notifications as read', () => {
    const { add, markAllRead, getNotifications } = setup()

    act(() => {
      add({ id: 'a', title: 'A' })
      add({ id: 'b', title: 'B' })
      add({ id: 'c', title: 'C' })
    })

    act(() => {
      markAllRead()
    })

    expect(getNotifications().every(n => n.read)).toBe(true)
  })

  it('is idempotent when all are already read', () => {
    const { add, markRead, markAllRead, find } = setup()

    let id: string
    act(() => {
      id = add({ title: 'Solo' })
    })

    act(() => { markRead(id) })
    const before = find(id)

    act(() => { markAllRead() })
    const after = find(id)

    // Same notification object wasn't re-created by markAllRead
    // (markAllRead skips notifications that are already read)
    expect(before).toBe(after)
  })

  // ── unreadCount ─────────────────────────────────────────────────

  it('starts with zero unread', () => {
    const { getUnreadCount } = setup()
    expect(getUnreadCount()).toBe(0)
  })

  it('reflects unread notifications after adding', () => {
    const { add, getUnreadCount } = setup()

    act(() => {
      add({ title: 'Unread 1' })
      add({ title: 'Unread 2' })
    })

    expect(getUnreadCount()).toBe(2)
  })

  it('decrements unread when marking as read', () => {
    const { add, markRead, getUnreadCount } = setup()

    let id: string
    act(() => {
      id = add({ title: 'Will read' })
      add({ title: 'Stays unread' })
    })
    expect(getUnreadCount()).toBe(2)

    act(() => { markRead(id) })
    expect(getUnreadCount()).toBe(1)
  })

  it('drops unread to zero after markAllRead', () => {
    const { add, markAllRead, getUnreadCount } = setup()

    act(() => {
      add({ title: 'A' })
      add({ title: 'B' })
      add({ title: 'C' })
    })
    expect(getUnreadCount()).toBe(3)

    act(() => { markAllRead() })
    expect(getUnreadCount()).toBe(0)
  })

  // ── Clear ───────────────────────────────────────────────────────

  it('clears all notifications', () => {
    const { add, clear, notificationsCount, getUnreadCount } = setup()

    act(() => {
      add({ title: 'A' })
      add({ title: 'B' })
    })
    expect(notificationsCount()).toBe(2)

    act(() => { clear() })
    expect(notificationsCount()).toBe(0)
    expect(getUnreadCount()).toBe(0)
  })

  // ── Storage Persistence ─────────────────────────────────────────

  it('persists to localStorage after adding', () => {
    const { add } = setup()

    act(() => {
      add({ id: 'persist-me', title: 'Persist test', type: 'warning' })
    })

    const raw = localStorage.getItem('eigencapital_notifications')
    expect(raw).not.toBeNull()

    const stored = JSON.parse(raw!)
    expect(stored).toHaveLength(1)
    expect(stored[0].id).toBe('persist-me')
    expect(stored[0].title).toBe('Persist test')
  })

  it('restores notifications from localStorage on mount', () => {
    const seed = [
      { id: 'saved-1', type: 'info', title: 'Restored', message: '', timestamp: 100, read: false },
      { id: 'saved-2', type: 'warning', title: 'Also restored', message: '', timestamp: 200, read: true },
    ]
    localStorage.setItem('eigencapital_notifications', JSON.stringify(seed))

    const { getNotifications } = setup()

    expect(getNotifications()).toHaveLength(2)
    expect(getNotifications()[0].id).toBe('saved-1')
    expect(getNotifications()[1].id).toBe('saved-2')
  })

  it('survives a re-mount (rerender with new provider)', () => {
    let addFn!: ReturnType<typeof useNotificationCenter>['add']

    function CaptureAdd() {
      addFn = useNotificationCenter().add
      return null
    }

    const { unmount } = render(
      <NotificationProvider><CaptureAdd /></NotificationProvider>,
    )

    act(() => {
      addFn({ id: 'survivor', title: 'Survived' })
    })

    unmount()

    // Mount a fresh provider — should read from localStorage
    function Reader() {
      const { notifications } = useNotificationCenter()
      return <div data-testid="count">{notifications.length}</div>
    }

    render(
      <NotificationProvider><Reader /></NotificationProvider>,
    )

    expect(screen.getByTestId('count').textContent).toBe('1')
  })

  it('handles corrupted localStorage gracefully', () => {
    localStorage.setItem('eigencapital_notifications', 'not-valid-json{{{')

    const { getNotifications } = setup()
    expect(getNotifications()).toEqual([])
  })

  it('starts empty when localStorage is missing', () => {
    localStorage.removeItem('eigencapital_notifications')

    const { getNotifications } = setup()
    expect(getNotifications()).toEqual([])
  })

  // ── Provider Error ──────────────────────────────────────────────

  it('throws when used outside NotificationProvider', () => {
    // renderHook calls the hook callback synchronously at render time,
    // which will throw because there's no NotificationProvider ancestor.
    expect(() => renderOutsideProvider()).toThrow(
      'useNotificationCenter must be used within a NotificationProvider',
    )
  })

  // ── Edge Cases ──────────────────────────────────────────────────

  it('can add after clear', () => {
    const { add, clear, getNotifications } = setup()

    act(() => { add({ id: 'a', title: 'A' }) })
    expect(getNotifications()).toHaveLength(1)

    act(() => { clear() })
    expect(getNotifications()).toHaveLength(0)

    act(() => { add({ id: 'b', title: 'B' }) })
    expect(getNotifications()).toHaveLength(1)
    expect(getNotifications()[0].title).toBe('B')
  })

  it('can re-add a previously cleared id', () => {
    const { add, clear, getNotifications } = setup()

    act(() => { add({ id: 'reused', title: 'First' }) })
    expect(getNotifications()).toHaveLength(1)

    act(() => { clear() })

    act(() => { add({ id: 'reused', title: 'Second' }) })
    expect(getNotifications()).toHaveLength(1)
    expect(getNotifications()[0].title).toBe('Second')
  })

  it('does not mutate existing notification objects when marking read', () => {
    const { add, markRead, find } = setup()

    let id: string
    act(() => { id = add({ title: 'Immutable' }) })

    const originalBefore = find(id)

    act(() => { markRead(id) })

    const originalAfter = find(id)

    // Different object reference → immutability preserved
    expect(originalBefore).not.toBe(originalAfter)
    // Old object still marks as unread
    expect(originalBefore!.read).toBe(false)
    // New object marks as read
    expect(originalAfter!.read).toBe(true)
  })
})
