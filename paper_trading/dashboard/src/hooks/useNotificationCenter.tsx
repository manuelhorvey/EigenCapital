import {
  createContext,
  useContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

// ── Types ─────────────────────────────────────────────────────────

export type NotificationType = 'success' | 'error' | 'warning' | 'info'

export interface Notification {
  id: string
  type: NotificationType
  title: string
  message?: string
  timestamp: number
  read: boolean
}

export interface NotificationOptions {
  type?: NotificationType
  title: string
  message?: string
  /** Optional explicit ID. Auto-generated if omitted. */
  id?: string
}

interface NotificationContextValue {
  notifications: Notification[]
  unreadCount: number
  add: (opts: NotificationOptions) => string
  markRead: (id: string) => void
  markAllRead: () => void
  clear: () => void
}

// ── Persistence ───────────────────────────────────────────────────

const STORAGE_KEY = 'eigencapital_notifications'

function saveToStorage(notifications: Notification[]) {
  try {
    // Keep only the most recent 200 to cap storage size
    const trimmed = notifications.slice(-200)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed))
  } catch {
    // localStorage full or unavailable
  }
}

function loadFromStorage(): Notification[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    return JSON.parse(raw) as Notification[]
  } catch {
    return []
  }
}

// ── Constants ─────────────────────────────────────────────────────

const MAX_HISTORY = 200

let _nextId = 0
function genId(): string {
  _nextId += 1
  return `notif-${_nextId}-${Date.now()}`
}

// ── Context ───────────────────────────────────────────────────────

const NotificationContext = createContext<NotificationContextValue | null>(null)

// ── Provider ───────────────────────────────────────────────────────

export function NotificationProvider({ children }: { children: ReactNode }) {
  const [notifications, setNotifications] = useState<Notification[]>(loadFromStorage)

  // Persist to sessionStorage whenever notifications change
  useEffect(() => {
    saveToStorage(notifications)
  }, [notifications])

  const add = useCallback((opts: NotificationOptions): string => {
    const id = opts.id ?? genId()
    const n: Notification = {
      id,
      type: opts.type ?? 'info',
      title: opts.title,
      message: opts.message,
      timestamp: Date.now(),
      read: false,
    }

    setNotifications(prev => {
      // Deduplicate by ID
      if (prev.some(p => p.id === id)) return prev
      const next = [...prev, n]
      return next.length > MAX_HISTORY ? next.slice(next.length - MAX_HISTORY) : next
    })

    return id
  }, [])

  const markRead = useCallback((id: string) => {
    setNotifications(prev =>
      prev.map(n => (n.id === id ? { ...n, read: true } : n)),
    )
  }, [])

  const markAllRead = useCallback(() => {
    setNotifications(prev =>
      prev.map(n => (n.read ? n : { ...n, read: true })),
    )
  }, [])

  const clear = useCallback(() => {
    setNotifications([])
    localStorage.removeItem(STORAGE_KEY)
  }, [])

  const unreadCount = useMemo(
    () => notifications.filter(n => !n.read).length,
    [notifications],
  )

  const value = useMemo(
    () => ({ notifications, unreadCount, add, markRead, markAllRead, clear }),
    [notifications, unreadCount, add, markRead, markAllRead, clear],
  )

  return (
    <NotificationContext.Provider value={value}>
      {children}
    </NotificationContext.Provider>
  )
}

// ── Hook ────────────────────────────────────────────────────────────

export function useNotificationCenter(): NotificationContextValue {
  const ctx = useContext(NotificationContext)
  if (!ctx) throw new Error('useNotificationCenter must be used within a NotificationProvider')
  return ctx
}
