import type { ReactNode } from 'react'

type PanelVariant = 'default' | 'elevated' | 'flat' | 'accent' | 'glass'

interface PanelProps {
  children: ReactNode
  className?: string
  padding?: 'md' | 'lg' | 'none'
  variant?: PanelVariant
  hoverable?: boolean
  onClick?: () => void
  leftAccent?: string
  /** Subtle gradient overlay on top */
  gradient?: boolean
  /** Glow color for accent variant (CSS color) */
  glowColor?: string
}

const paddingMap = {
  md: 'p-3.5 sm:p-4',
  lg: 'p-4 sm:p-5',
  none: '',
}

const variantStyles: Record<PanelVariant, string> = {
  default: 'bg-panel border border-default shadow-panel',
  elevated: 'bg-panel border border-default shadow-card',
  flat: 'bg-panel border border-default',
  accent: 'bg-panel border border-default shadow-panel border-t-accent-emerald/40',
  glass: 'bg-glass border border-default/60 shadow-panel backdrop-blur-xl',
}

const gradientOverlay = (
  <span
    className="absolute inset-0 rounded-lg pointer-events-none overflow-hidden"
    aria-hidden
  >
    <span className="absolute inset-0 bg-gradient-to-b from-white/[0.02] to-transparent" />
  </span>
)

export default function Panel({
  children,
  className = '',
  padding = 'md',
  variant = 'default',
  hoverable = false,
  onClick,
  leftAccent,
  gradient = false,
  glowColor,
}: PanelProps) {
  const hoverStyles = hoverable
    ? 'cursor-pointer hover:border-strong hover:shadow-card hover:-translate-y-0.5 transition-all duration-200 ease-out'
    : ''

  const glowStyles = glowColor
    ? `shadow-[0_0_15px_-3px_${glowColor}]`
    : ''

  return (
    <div
      onClick={onClick}
      className={[
        'rounded-lg relative overflow-hidden',
        variantStyles[variant],
        paddingMap[padding],
        hoverStyles,
        glowStyles,
        leftAccent ? 'border-l-2' : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      style={leftAccent ? { borderLeftColor: leftAccent } : undefined}
    >
      {/* Subtle gradient overlay for depth */}
      {gradient && gradientOverlay}

      {/* Left accent border effect */}
      {leftAccent && (
        <span
          className="absolute left-0 top-0 bottom-0 w-0.5 rounded-l-lg"
          style={{
            background: `linear-gradient(to bottom, ${leftAccent}, transparent)`,
          }}
        />
      )}

      <div className="relative z-0">
        {children}
      </div>
    </div>
  )
}
