import type { ReactNode } from 'react'

type PanelVariant = 'default' | 'elevated' | 'flat' | 'accent'

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
  flat: 'bg-panel border border-default',
  accent: 'bg-panel border border-default shadow-panel border-t-accent-emerald/50',
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
    ? 'cursor-pointer hover:border-strong transition-colors duration-200'
    : ''

  return (
    <div
      onClick={onClick}
      className={[
        'rounded-lg',
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
