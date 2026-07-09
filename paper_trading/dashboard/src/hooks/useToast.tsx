import {
  createContext,
  useContext,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'

// ── Types ─────────────────────────────────────────────────────────

export type ToastType = 'success' | 'error' | 'warning' | 'info'

export interface Toast {
  id: string
  type: ToastType
  title: string
  message?: string
  /** Auto-dismiss duration in ms. Default 4000. 0 = persistent (must be manually dismissed). */
  duration?: number
  /** Optional action button rendered inside the toast. */
  action?: {
    label: string
    onClick: () => void
  }
  /** Timestamp for ordering. */
  createdAt: number
}

export interface ToastOptions {
  type?: ToastType
  title: string
  message?: string
  duration?: number
  action?: Toast['action']
  /** Unique ID. Auto-generated if omitted. */
  id?: string
}

interface ToastContextValue {
  toasts: Toast[]
  toast: (opts: ToastOptions) => string
  dismiss: (id: string) => void
  clear: () => void
}

// ── Constants ──────────────────────────────────────────────────────

const DEFAULT_DURATION = 4_000
const MAX_VISIBLE = 5

let _nextId = 0
function genId(): string {
  _nextId += 1
  return `toast-${_nextId}-${Date.now()}`
}

// ── Context ────────────────────────────────────────────────────────

const ToastContext = createContext<ToastContextValue | null>(null)

// ── Provider ───────────────────────────────────────────────────────

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  const dismiss = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id))
    const timer = timersRef.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timersRef.current.delete(id)
    }
  }, [])

  const toast = useCallback((opts: ToastOptions): string => {
    const id = opts.id ?? genId()
    const newToast: Toast = {
      id,
      type: opts.type ?? 'info',
      title: opts.title,
      message: opts.message,
      duration: opts.duration ?? DEFAULT_DURATION,
      action: opts.action,
      createdAt: Date.now(),
    }

    setToasts(prev => {
      const next = [...prev, newToast]
      // Keep only the most recent MAX_VISIBLE toasts
      return next.length > MAX_VISIBLE ? next.slice(next.length - MAX_VISIBLE) : next
    })

    // Auto-dismiss
    if (newToast.duration && newToast.duration > 0) {
      const timer = setTimeout(() => {
        dismiss(id)
      }, newToast.duration)
      timersRef.current.set(id, timer)
    }

    return id
  }, [dismiss])

  const clear = useCallback(() => {
    setToasts([])
    for (const timer of timersRef.current.values()) {
      clearTimeout(timer)
    }
    timersRef.current.clear()
  }, [])

  // Cleanup timers on unmount to prevent orphaned timeout callbacks
  useEffect(() => {
    return () => {
      for (const timer of timersRef.current.values()) {
        clearTimeout(timer)
      }
      timersRef.current.clear()
    }
  }, [])

  const value = useMemo(
    () => ({ toasts, toast, dismiss, clear }),
    [toasts, toast, dismiss, clear],
  )

  return (
    <ToastContext.Provider value={value}>
      {children}
    </ToastContext.Provider>
  )
}

// ── Hook ────────────────────────────────────────────────────────────

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within a ToastProvider')
  return ctx
}
