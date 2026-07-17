import { useState, useMemo, useCallback, useEffect } from 'react'
import {
  Bell,
  X,
  CheckCheck,
  Trash2,
  AlertTriangle,
  Info,
  CheckCircle,
  AlertCircle,
} from 'lucide-react'
import { useNotificationCenter, type NotificationType } from '../hooks/useNotificationCenter'
import useFocusTrap from '../hooks/useFocusTrap'

// ── Filter options ────────────────────────────────────────────────

type Filter = 'all' | NotificationType

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'error', label: 'Errors' },
  { id: 'warning', label: 'Warnings' },
  { id: 'success', label: 'Success' },
  { id: 'info', label: 'Info' },
]

// ── Helpers ───────────────────────────────────────────────────────

function typeIcon(type: NotificationType) {
  switch (type) {
    case 'error':   return AlertCircle
    case 'warning': return AlertTriangle
    case 'success': return CheckCircle
    case 'info':    return Info
  }
}

function typeColor(type: NotificationType): string {
  switch (type) {
    case 'error':   return 'var(--color-gov-red)'
    case 'warning': return 'var(--color-gov-yellow)'
    case 'success': return 'var(--color-gov-green)'
    case 'info':    return 'var(--color-accent-blue)'
  }
}

function relativeTime(ts: number): string {
  const diff = Date.now() - ts
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.round(diff / 3_600_000)}h ago`
  return `${Math.round(diff / 86_400_000)}d ago`
}

// ── Props ─────────────────────────────────────────────────────────

interface NotificationCenterProps {
  open: boolean
  onClose: () => void
}

// ── Component ─────────────────────────────────────────────────────

/**
 * Notification center slide-over panel with severity filter, history, and read/unread state.
 * Bridges the toast system and monitor alerts into a persistent notification history.
 */
export default function NotificationCenter({ open, onClose }: NotificationCenterProps) {
  const { notifications, unreadCount, markRead, markAllRead, clear } = useNotificationCenter()
  const [filter, setFilter] = useState<Filter>('all')

  const filtered = useMemo(() => {
    if (filter === 'all') return notifications
    return notifications.filter(n => n.type === filter)
  }, [notifications, filter])

  const handleMarkRead = useCallback((id: string) => {
    markRead(id)
  }, [markRead])

  const panelRef = useFocusTrap()

  // Escape to close
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <>
      {/* Overlay backdrop */}
      <div className="fixed inset-0 z-40 bg-black/40 sm:bg-black/30" onClick={onClose} aria-hidden="true" />

      {/* Panel */}
      <div
        ref={panelRef}
        className="fixed inset-y-0 right-0 z-50 w-full sm:w-[380px] bg-app border-l border-default shadow-2xl flex flex-col animate-fade-in"
        role="dialog"
        aria-modal="true"
        aria-label="Notification center"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-default shrink-0">
          <div className="flex items-center gap-2">
            <Bell className="w-4 h-4 text-secondary" strokeWidth={1.5} />
            <h2 className="text-sm font-semibold text-primary">Notifications</h2>
            {unreadCount > 0 && (
              <span className="inline-flex items-center justify-center min-w-[18px] h-4 px-1 rounded-full text-[9px] font-bold leading-none bg-accent-emerald/15 text-accent-emerald border border-accent-emerald/25">
                {unreadCount}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            {unreadCount > 0 && (
              <button
                type="button"
                onClick={markAllRead}
                className="min-h-[28px] min-w-[28px] inline-flex items-center justify-center rounded text-tertiary hover:text-primary hover:bg-panel transition-colors focus-ring"
                aria-label="Mark all as read"
                title="Mark all as read"
              >
                <CheckCheck className="w-3.5 h-3.5" strokeWidth={1.5} />
              </button>
            )}
            {notifications.length > 0 && (
              <button
                type="button"
                onClick={clear}
                className="min-h-[28px] min-w-[28px] inline-flex items-center justify-center rounded text-tertiary hover:text-gov-red hover:bg-gov-red-muted/30 transition-colors focus-ring"
                aria-label="Clear all notifications"
                title="Clear all"
              >
                <Trash2 className="w-3.5 h-3.5" strokeWidth={1.5} />
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="min-h-[28px] min-w-[28px] inline-flex items-center justify-center rounded text-tertiary hover:text-primary hover:bg-panel transition-colors focus-ring ml-1"
              aria-label="Close notification center"
            >
              <X className="w-3.5 h-3.5" strokeWidth={1.5} />
            </button>
          </div>
        </div>

        {/* Filter tabs */}
        <div className="flex items-center gap-0.5 px-3 py-2 border-b border-default/60 shrink-0 overflow-x-auto">
          {FILTERS.map(f => (
            <button
              key={f.id}
              type="button"
              onClick={() => setFilter(f.id)}
              className={`px-2 py-1 text-2xs font-medium rounded-md transition-colors shrink-0 focus-ring ${
                filter === f.id
                  ? 'bg-panel text-primary border border-strong/40'
                  : 'text-tertiary hover:text-secondary hover:bg-panel/60'
              }`}
            >
              {f.label}
              {f.id !== 'all' && (
                <span className="ml-1 text-muted">
                  {notifications.filter(n => n.type === f.id).length}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Notification list */}
        <div className="flex-1 overflow-y-auto">
          {filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
              <Bell className="w-8 h-8 text-muted/40 mb-3" strokeWidth={1} />
              <p className="text-xs text-tertiary font-medium">
                {filter === 'all' ? 'No notifications yet' : `No ${filter} notifications`}
              </p>
              <p className="text-2xs text-muted mt-1">
                {filter === 'all'
                  ? 'System alerts, trade rejections, and status changes will appear here'
                  : 'Try switching to a different filter'}
              </p>
            </div>
          ) : (
            <div className="divide-y divide-default/40">
              {filtered.map(n => {
                const Icon = typeIcon(n.type)
                const color = typeColor(n.type)
                return (
                  <div
                    key={n.id}
                    className={`flex items-start gap-3 px-4 py-3 transition-colors ${
                      !n.read ? 'bg-interactive-selected/30' : 'hover:bg-panel/40'
                    }`}
                  >
                    {/* Type icon */}
                    <span className="shrink-0 mt-0.5" style={{ color }}>
                      <Icon className="w-3.5 h-3.5" strokeWidth={1.5} />
                    </span>

                    {/* Content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-start justify-between gap-2">
                        <span className={`text-xs ${!n.read ? 'font-semibold text-primary' : 'font-medium text-secondary'}`}>
                          {n.title}
                        </span>
                        <span className="text-[9px] text-muted font-mono shrink-0 mt-0.5">
                          {relativeTime(n.timestamp)}
                        </span>
                      </div>
                      {n.message && (
                        <p className="text-2xs text-tertiary mt-0.5 line-clamp-2">{n.message}</p>
                      )}
                    </div>

                    {/* Unread indicator */}
                    {!n.read && (
                      <button
                        type="button"
                        onClick={() => handleMarkRead(n.id)}
                        className="shrink-0 mt-1 min-h-[18px] min-w-[18px] inline-flex items-center justify-center rounded-full hover:bg-panel transition-colors focus-ring"
                        aria-label={`Mark "${n.title}" as read`}
                        title="Mark as read"
                      >
                        <span className="w-2 h-2 rounded-full bg-accent-emerald" />
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Footer summary */}
        {notifications.length > 0 && (
          <div className="px-4 py-2 border-t border-default/60 text-[9px] text-muted font-mono text-center shrink-0">
            {notifications.length} total{unreadCount > 0 ? ` · ${unreadCount} unread` : ''}
          </div>
        )}
      </div>
    </>
  )
}
