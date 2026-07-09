import { Inbox, SearchSlash, BarChart3, AlertCircle, Clock, Activity } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import Button from './Button'

// ── Icon registry ──────────────────────────────────────────────────

const ICON_MAP: Record<string, LucideIcon> = {
  inbox: Inbox,
  search: SearchSlash,
  chart: BarChart3,
  warning: AlertCircle,
  clock: Clock,
  activity: Activity,
}

const ICON_COLORS: Record<string, string> = {
  inbox: 'text-tertiary/40',
  search: 'text-tertiary/40',
  chart: 'text-accent-blue/50',
  warning: 'text-gov-yellow/50',
  clock: 'text-accent-purple/50',
  activity: 'text-accent-emerald/50',
}

// ── Props ──────────────────────────────────────────────────────────

interface EmptyStateProps {
  /** Primary message displayed in the empty state. */
  message: string
  /** Optional hint text shown below the message. */
  hint?: string
  /** When true, renders a more compact version for inline use. */
  compact?: boolean
  /** When true, shows a "no results" icon instead of the generic inbox icon. */
  filtered?: boolean
  /** Icon variant. Auto-selected based on `filtered` when omitted. */
  icon?: 'inbox' | 'search' | 'chart' | 'warning' | 'clock' | 'activity'
  /** Optional call-to-action button. */
  action?: {
    label: string
    onClick: () => void
  }
  /** Optional className for the outer container. */
  className?: string
}

// ── Component ──────────────────────────────────────────────────────

/**
 * Empty-state placeholder shown when a list or section has no data.
 * Supports icon variants, contextual hints, and optional CTA buttons.
 *
 * @param filtered - When true, shows a "no results" icon.
 * @param icon - Override the icon variant (auto-selected when omitted).
 * @param action - Optional CTA button with label and onClick.
 * @param compact - Reduced padding for inline/panel use.
 */
export default function EmptyState({
  message,
  hint,
  compact = false,
  filtered = false,
  icon,
  action,
  className = '',
}: EmptyStateProps) {
  // Determine icon: explicit icon > filtered auto-detect > default inbox
  const iconKey = icon ?? (filtered ? 'search' : 'inbox')
  const Icon = ICON_MAP[iconKey] ?? Inbox
  const iconColor = ICON_COLORS[iconKey] ?? 'text-tertiary/40'

  return (
    <div
      className={[
        'flex flex-col items-center justify-center text-center',
        compact ? 'py-8 px-4' : 'py-16 px-6',
        className,
      ].join(' ')}
    >
      {/* Icon */}
      <div className={`mb-3 ${compact ? '' : 'mb-4'}`}>
        <Icon
          className={`${iconColor} ${compact ? 'w-6 h-6' : 'w-10 h-10'} transition-colors duration-200`}
          strokeWidth={1.25}
        />
      </div>

      {/* Message */}
      <p className={`text-tertiary font-semibold ${compact ? 'text-xs' : 'text-sm'} leading-relaxed max-w-xs`}>
        {message}
      </p>

      {/* Hint */}
      {hint != null && (
        <p className="text-muted text-[11px] mt-2 max-w-xs leading-relaxed">
          {hint}
        </p>
      )}

      {/* CTA */}
      {action && (
        <div className="mt-4">
          <Button variant="secondary" size="sm" onClick={action.onClick}>
            {action.label}
          </Button>
        </div>
      )}
    </div>
  )
}
