import { memo } from 'react'
import { X, CheckCircle, AlertCircle, AlertTriangle, Info } from 'lucide-react'
import { useToast, type ToastType } from '../../hooks/useToast'

// ── Severity configuration ────────────────────────────────────────

const SEVERITY_CONFIG: Record<ToastType, {
  icon: typeof CheckCircle
  containerClass: string
  iconClass: string
  borderClass: string
}> = {
  success: {
    icon: CheckCircle,
    containerClass: 'border-gov-green/30 bg-gov-green-muted2',
    iconClass: 'text-gov-green',
    borderClass: 'border-l-gov-green',
  },
  error: {
    icon: AlertCircle,
    containerClass: 'border-gov-red/30 bg-gov-red-muted2',
    iconClass: 'text-gov-red',
    borderClass: 'border-l-gov-red',
  },
  warning: {
    icon: AlertTriangle,
    containerClass: 'border-gov-yellow/30 bg-gov-yellow-muted2',
    iconClass: 'text-gov-yellow',
    borderClass: 'border-l-gov-yellow',
  },
  info: {
    icon: Info,
    containerClass: 'border-accent-blue/30 bg-accent-blue/8',
    iconClass: 'text-accent-blue',
    borderClass: 'border-l-accent-blue',
  },
}

// ── Single Toast Item ──────────────────────────────────────────────

interface ToastItemProps {
  id: string
  type: ToastType
  title: string
  message?: string
  action?: { label: string; onClick: () => void }
  onDismiss: (id: string) => void
}

const ToastItem = memo(function ToastItem({
  id, type, title, message, action, onDismiss,
}: ToastItemProps) {
  const config = SEVERITY_CONFIG[type]
  const Icon = config.icon

  // Respect reduced motion
  const animationStyle =
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
      ? undefined
      : { animation: 'slide-up 0.3s ease-out' }

  return (
    <div
      role="alert"
      className="relative w-full max-w-sm rounded-lg border shadow-card bg-surface border-default flex items-start gap-3 p-3.5 pointer-events-auto"
      style={animationStyle}
    >
      {/* Left accent bar */}
      <span
        className={`absolute left-0 top-2 bottom-2 w-0.5 rounded-full ${config.iconClass}`}
      />

      <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${config.iconClass}`} strokeWidth={2} />

      <div className="flex-1 min-w-0">
        <p className="text-xs font-semibold text-primary leading-snug">{title}</p>
        {message && (
          <p className="text-2xs text-tertiary mt-0.5 leading-relaxed">{message}</p>
        )}
        {action && (
          <button
            type="button"
            onClick={action.onClick}
            className="mt-1.5 text-2xs font-semibold text-accent-emerald hover:text-accent-emerald/80 transition-colors"
          >
            {action.label}
          </button>
        )}
      </div>

      <button
        type="button"
        onClick={() => onDismiss(id)}
        className="shrink-0 p-0.5 rounded hover:bg-panel transition-colors -mr-0.5 -mt-0.5"
        aria-label="Dismiss notification"
      >
        <X className="w-3 h-3 text-tertiary" strokeWidth={2} />
      </button>

      {/* Auto-dismiss progress bar */}
      <span
        className="absolute bottom-0 left-0 right-0 h-0.5 rounded-b-lg overflow-hidden"
      >
        <span
          className="block h-full animate-shrink"
          style={{
            animation: 'shrink 4s linear forwards',
            backgroundColor: 'currentColor',
            opacity: 0.15,
          }}
        />
      </span>
    </div>
  )
})

// ── Toast Container ────────────────────────────────────────────────

/**
 * Fixed-position toast notification overlay.
 * Renders the active toast stack with auto-dismiss, severity styling,
 * and optional action buttons.
 */
function ToastContainerInner() {
  const { toasts, dismiss } = useToast()

  if (toasts.length === 0) return null

  return (
    <div
      className="fixed top-3 right-3 z-[100] flex flex-col gap-2 pointer-events-none"
      aria-live="polite"
      aria-label="Notifications"
    >
      {toasts.map(t => (
        <div key={t.id} className="pointer-events-auto">
          <ToastItem
            id={t.id}
            type={t.type}
            title={t.title}
            message={t.message}
            action={t.action}
            onDismiss={dismiss}
          />
        </div>
      ))}
    </div>
  )
}

export const ToastContainer = memo(ToastContainerInner)
