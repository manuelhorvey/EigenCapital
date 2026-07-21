import { useState, useId, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'

interface ExpandableSectionProps {
  title: string
  children: ReactNode
  defaultOpen?: boolean
  /** Storage key for persisting expanded state across sessions */
  storageKey?: string
  badge?: ReactNode
  className?: string
}

/**
 * Progressive disclosure section — collapses content behind a header toggle.
 * Useful for reducing cognitive load on dense dashboards: secondary metrics,
 * debug info, historical context, or optional panels.
 *
 * Uses `max-h-[9999px]` for the collapse animation — tall enough to avoid
 * clipping most dashboard panels. For extremely tall content (>9999px),
 * pass a custom `className` with a higher `max-h` value.
 *
 * Usage:
 *   <ExpandableSection title="Detailed Metrics" storageKey="detailed-metrics">
 *     <ExpensiveChart />
 *   </ExpandableSection>
 */
export default function ExpandableSection({
  title,
  children,
  defaultOpen = false,
  storageKey,
  badge,
  className = '',
}: ExpandableSectionProps) {
  const id = useId()
  const contentId = `expand-content-${id}`

  const [open, setOpen] = useState(() => {
    if (storageKey) {
      try {
        const stored = localStorage.getItem(`expand_${storageKey}`)
        if (stored !== null) return stored === 'true'
      } catch { /* ignore */ }
    }
    return defaultOpen
  })

  const toggle = () => {
    const next = !open
    setOpen(next)
    if (storageKey) {
      try {
        localStorage.setItem(`expand_${storageKey}`, String(next))
      } catch { /* ignore */ }
    }
  }

  return (
    <div className={className}>
      <button
        type="button"
        onClick={toggle}
        className="w-full flex items-center gap-2 px-3 py-2 rounded-md hover:bg-panel/40 transition-colors text-left focus-ring group"
        aria-expanded={open}
        aria-controls={contentId}
      >
        <ChevronDown
          className={`w-3.5 h-3.5 text-tertiary transition-transform duration-200 ${
            open ? 'rotate-0' : '-rotate-90'
          }`}
          strokeWidth={2}
        />
        <span className="text-xs font-medium text-secondary group-hover:text-primary transition-colors">
          {title}
        </span>
        {badge && (
          <span className="ml-auto">{badge}</span>
        )}
      </button>
      <div
        id={contentId}
        role="region"
        className={`overflow-hidden transition-all duration-200 ease-out ${
          open ? 'max-h-[9999px] opacity-100' : 'max-h-0 opacity-0'
        }`}
      >
        <div className="pt-2 pb-1 px-3">
          {children}
        </div>
      </div>
    </div>
  )
}
