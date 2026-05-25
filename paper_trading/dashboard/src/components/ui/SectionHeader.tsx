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
  emerald: 'bg-accent-emerald/60 shadow-glow-emerald',
  blue: 'bg-accent-blue/60',
  purple: 'bg-accent-purple/60',
  amber: 'bg-accent-amber/60',
  indigo: 'bg-accent-indigo/60',
  neutral: 'bg-gov-init/50',
}

const titleSize = {
  sm: 'text-xs',
  md: 'section-title',
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
        border ? 'pb-2.5 mb-3 border-b border-default' : 'mb-3',
        className,
      ].join(' ')}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${accentDot[accent]}`} />
        <div className="min-w-0">
          <h2 className={[titleSize[size], 'truncate'].join(' ')}>{title}</h2>
          {subtitle && <p className="text-[10px] text-tertiary font-mono truncate">{subtitle}</p>}
        </div>
      </div>
      {meta != null && <div className="shrink-0">{meta}</div>}
    </div>
  )
}
