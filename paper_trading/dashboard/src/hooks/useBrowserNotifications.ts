import { useCallback, useEffect, useState } from 'react'

// ── Types ─────────────────────────────────────────────────────────

export interface BrowserNotificationOptions {
  title: string
  body?: string
  /** URL to navigate to when the user clicks the notification. */
  onClickUrl?: string
  /** Icon URL (defaults to `/favicon.ico`) */
  icon?: string
  /** Tag for grouping — replaces any previous notification with the same tag. */
  tag?: string
  /** Whether to bypass the `enabled` opt-out check. Used for critical alerts. */
  force?: boolean
}

export interface UseBrowserNotificationsReturn {
  /** Whether the Notification API is available in this browser. */
  readonly supported: boolean
  /** Current Notification.permission value. */
  readonly permission: NotificationPermission
  /** Whether desktop notifications are enabled (user opt-in toggle). */
  readonly enabled: boolean
  /** Toggle desktop notifications on/off. Persisted to localStorage. */
  setEnabled: (enabled: boolean) => void
  /** Request permission from the browser. Must be called from a user gesture. */
  requestPermission: () => Promise<NotificationPermission>
  /** Fire a desktop notification if supported, permitted, and enabled. */
  notify: (opts: BrowserNotificationOptions) => void
}

// ── Constants ─────────────────────────────────────────────────────

const STORAGE_KEY = 'ec-desktop-notifications'
const DEFAULT_ICON = '/favicon.ico'
const TAG_PREFIX = 'ec-notif-'

// ── Hook ──────────────────────────────────────────────────────────

/**
 * Hook wrapping the browser `Notification` API.
 *
 * - Requests permission on first call to `notify` if permission is `'default'`
 *   (but the browser may still require a user gesture).
 * - Persists an opt-out toggle to `localStorage` so users can disable
 *   desktop notifications without revoking the browser permission.
 * - Fires via `new Notification(...)` which works even when the tab is
 *   not focused — critical for trading alerts.
 */
export function useBrowserNotifications(): UseBrowserNotificationsReturn {
  const supported =
    typeof window !== 'undefined' && 'Notification' in window

  const [permission, setPermission] = useState<NotificationPermission>(
    () => {
      if (!supported) return 'denied'
      return Notification.permission
    },
  )

  const [enabled, setEnabledState] = useState(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      // Default to enabled if never explicitly set
      return stored !== null ? stored === 'true' : true
    } catch {
      return true
    }
  })

  // Sync permission state from Notification.permission and subscribe to
  // external changes (e.g. user changes site permission in browser settings).
  // Uses the Permissions API when available, falls back to one-shot init.
  useEffect(() => {
    if (!supported) return
    let cancelled = false

    const sync = () => {
      if (cancelled) return
      setPermission(Notification.permission)
    }
    sync()

    try {
      navigator.permissions
        .query({ name: 'notifications' as PermissionName })
        .then(status => {
          if (!cancelled) status.onchange = sync
        })
        .catch(() => {
          // Permissions API not available or query rejected
        })
    } catch {
      // navigator.permissions may be undefined (older browsers)
    }

    return () => {
      cancelled = true
    }
  }, [supported])

  const setEnabled = useCallback((val: boolean) => {
    setEnabledState(val)
    try {
      localStorage.setItem(STORAGE_KEY, String(val))
    } catch {
      // localStorage full or unavailable
    }
  }, [])

  const requestPermission = useCallback(async () => {
    if (!supported) return 'denied' as NotificationPermission
    try {
      const result = await Notification.requestPermission()
      setPermission(result)
      return result
    } catch {
      return 'denied' as NotificationPermission
    }
  }, [supported])

  const notify = useCallback(
    (opts: BrowserNotificationOptions) => {
      if (!supported || permission !== 'granted') return
      if (!opts.force && !enabled) return

      try {
        const n = new Notification(opts.title, {
          body: opts.body,
          icon: opts.icon ?? DEFAULT_ICON,
          tag: opts.tag ?? `${TAG_PREFIX}${opts.title}`,
        })

        // Click → focus the dashboard tab
        if (opts.onClickUrl) {
          n.addEventListener('click', () => {
            window.focus()
            // Only navigate if we're not already at the target
            const cleanCurrent = window.location.href.split('?')[0].split('#')[0]
            const cleanTarget = opts.onClickUrl!.split('?')[0].split('#')[0]
            if (cleanCurrent !== cleanTarget) {
              window.location.href = opts.onClickUrl!
            }
            n.close()
          })
        }

        // Close auto-dismiss after timeout (notifications persist by default
        // until the user clicks or closes them, which is the desired behavior
        // for trading alerts so they don't vanish)
      } catch {
        // Notification constructor may throw if permission was revoked
        // between check and construction
      }
    },
    [supported, permission, enabled],
  )

  return { supported, permission, enabled, setEnabled, requestPermission, notify } as const
}

/**
 * Generate a tag for grouping related notifications so newer ones
 * replace older ones of the same type (prevents notification spam).
 */
export function notifTag(category: string): string {
  return `${TAG_PREFIX}${category}`
}
