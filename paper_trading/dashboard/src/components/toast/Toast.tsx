import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { CheckCircle2, Info, AlertTriangle, XCircle, X } from 'lucide-react'

export type ToastVariant = 'success' | 'info' | 'warning' | 'error'

export interface ToastOptions {
  title: string
  description?: string
  variant?: ToastVariant
  /** Auto-dismiss delay in ms. 0 = sticky. */
  duration?: number
}

interface ToastItem extends ToastOptions {
  id: number
}

interface ToastContextValue {
  toast: (options: ToastOptions) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

let nextId = 1

const variantIcon: Record<ToastVariant, ReactNode> = {
  success: <CheckCircle2 className="w-4 h-4 text-gov-green" strokeWidth={2} />,
  info: <Info className="w-4 h-4 text-accent-blue" strokeWidth={2} />,
  warning: <AlertTriangle className="w-4 h-4 text-gov-yellow" strokeWidth={2} />,
  error: <XCircle className="w-4 h-4 text-gov-red" strokeWidth={2} />,
}

const variantBorder: Record<ToastVariant, string> = {
  success: 'border-l-gov-green',
  info: 'border-l-accent-blue',
  warning: 'border-l-gov-yellow',
  error: 'border-l-gov-red',
}

const DEFAULT_DURATION = 5000

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map())

  // Clear pending timers on unmount to avoid setState-after-unmount warnings
  useEffect(() => {
    const map = timers.current
    return () => {
      for (const t of map.values()) clearTimeout(t)
      map.clear()
    }
  }, [])

  const dismiss = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id))
    const timer = timers.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.current.delete(id)
    }
  }, [])

  const toast = useCallback(
    (options: ToastOptions) => {
      const id = nextId++
      setToasts(prev => [...prev.slice(-3), { id, ...options }])
      const duration = options.duration ?? DEFAULT_DURATION
      if (duration > 0) {
        timers.current.set(id, setTimeout(() => dismiss(id), duration))
      }
    },
    [dismiss],
  )

  const value = { toast }

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* aria-live region: polite so async feedback is announced without interrupting */}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 w-[calc(100vw-2rem)] max-w-sm pointer-events-none"
      >
        {toasts.map(t => (
          <div
            key={t.id}
            role="status"
            className={`pointer-events-auto relative overflow-hidden rounded-lg bg-card border border-default shadow-card animate-slide-up border-l-2 ${variantBorder[t.variant ?? 'info']}`}
          >
            <div className="flex items-start gap-2.5 px-3 py-2.5">
              <span className="mt-px shrink-0">{variantIcon[t.variant ?? 'info']}</span>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold text-primary leading-snug">{t.title}</p>
                {t.description != null && (
                  <p className="text-[11px] text-tertiary mt-0.5 leading-snug">{t.description}</p>
                )}
              </div>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                className="shrink-0 p-1 -m-1 rounded-md text-tertiary hover:text-primary hover:bg-panel transition-colors focus-ring"
                aria-label="Dismiss notification"
              >
                <X className="w-3 h-3" strokeWidth={2} />
              </button>
            </div>
            {/* Auto-dismiss progress indicator */}
            {(t.duration ?? DEFAULT_DURATION) > 0 && (
              <span
                className="absolute bottom-0 left-0 right-0 h-0.5 bg-accent-emerald/50 origin-left"
                style={{
                  animation: `toast-progress ${(t.duration ?? DEFAULT_DURATION)}ms linear forwards`,
                }}
              />
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}
