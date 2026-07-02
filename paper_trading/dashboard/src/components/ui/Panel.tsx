import type { ReactNode } from 'react'

/**
 * Panel — the operator-console's standard surface.
 *
 * Two visual variants:
 *   - default: hairline rule + 4px corner + low-elevation inset shadow
 *   - elevated: same boundary + a higher-elevation outer shadow;
 *     use for cards that need to lift above other panels in the
 *     same row (modals, large dialogs, the deepest drill-down cards).
 *
 * History: pre-Phase 9 Panel supported 5 variants ('default',
 * 'elevated', 'flat', 'accent', 'glass') and ornamental props
 * (gradient overlay, glow color, left accent border). Audit step 2
 * collapsed this to two visual surfaces. After that work, no source
 * file in the dashboard references non-'default' variants or those
 * ornamental props — they're kept off the API surface here so the
 * collapse is permanent.
 */

type PanelVariant = 'default' | 'elevated'

interface PanelProps {
  children: ReactNode
  className?: string
  padding?: 'md' | 'lg' | 'none'
  variant?: PanelVariant
  hoverable?: boolean
  onClick?: () => void
}

const paddingMap = {
  md: 'p-3.5 sm:p-4',
  lg: 'p-4 sm:p-5',
  none: '',
}

const variantStyles: Record<PanelVariant, string> = {
  default: 'bg-panel border border-default shadow-panel',
  elevated: 'bg-panel border border-default shadow-card',
}

export default function Panel({
  children,
  className = '',
  padding = 'md',
  variant = 'default',
  hoverable = false,
  onClick,
}: PanelProps) {
  const hoverStyles = hoverable
    ? 'cursor-pointer hover:border-strong hover:shadow-card hover:-translate-y-0.5 transition-all duration-200 ease-out'
    : ''

  return (
    <div
      onClick={onClick}
      className={[
        'rounded-lg relative',
        variantStyles[variant],
        paddingMap[padding],
        hoverStyles,
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {children}
    </div>
  )
}
