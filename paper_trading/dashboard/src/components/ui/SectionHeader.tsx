import type { ReactNode } from 'react'

interface SectionHeaderProps {
  title: string
  subtitle?: string
  accent?: 'emerald' | 'blue' | 'purple' | 'amber' | 'indigo' | 'neutral'
  meta?: ReactNode
  className?: string
  border?: boolean
  size?: 'sm' | 'md'
}

const accentDot: Record<NonNullable<SectionHeaderProps['accent']>, string> = {
  emerald: 'bg-accent-emerald',
  blue: 'bg-accent-blue',
  purple: 'bg-accent-purple',
  amber: 'bg-accent-amber',
  indigo: 'bg-accent-indigo',
  neutral: 'bg-gov-init/60',
}

const titleSize = {
  sm: 'text-xs',
  md: 'text-sm',
}

export default function SectionHeader({
  title,
  subtitle,
  accent = 'emerald',
  meta,
  className = '',
  border = false,
  size = 'md',
}: SectionHeaderProps) {
  return (
    <div
      className={[
        'flex items-center justify-between gap-3',
        border ? 'pb-3 mb-3 border-b border-default' : 'mb-3',
        className,
      ].join(' ')}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className={`w-2 h-2 rounded-full shrink-0 opacity-70 ${accentDot[accent]}`} />
        <div className="min-w-0">
          <h2 className={[titleSize[size], 'font-semibold tracking-tight text-primary truncate'].join(' ')}>{title}</h2>
          {subtitle && <p className="text-[10px] text-tertiary font-mono truncate mt-0.5">{subtitle}</p>}
        </div>
      </div>
      {meta != null && <div className="shrink-0">{meta}</div>}
    </div>
  )
}
