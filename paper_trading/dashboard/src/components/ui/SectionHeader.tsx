import type { ReactNode } from 'react'

interface SectionHeaderProps {
  title: string
  subtitle?: string
  accent?: 'emerald' | 'blue' | 'purple' | 'amber' | 'indigo' | 'pink' | 'neutral'
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
  pink: 'bg-accent-pink',
  neutral: 'bg-gov-init/60',
}

const accentGlow: Record<NonNullable<SectionHeaderProps['accent']>, string> = {
  emerald: 'shadow-[0_0_6px_rgba(45,211,191,0.4)]',
  blue: 'shadow-[0_0_6px_rgba(96,165,250,0.4)]',
  purple: 'shadow-[0_0_6px_rgba(167,139,250,0.4)]',
  amber: 'shadow-[0_0_6px_rgba(251,191,36,0.4)]',
  indigo: 'shadow-[0_0_6px_rgba(129,140,248,0.4)]',
  pink: 'shadow-[0_0_6px_rgba(244,114,182,0.4)]',
  neutral: 'shadow-[0_0_6px_rgba(100,116,139,0.2)]',
}

const titleSize = {
  sm: 'text-sm',
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
        border ? 'pb-3 mb-3 border-b border-default' : 'mb-2.5',
        className,
      ].join(' ')}
    >
      <div className="flex items-center gap-2.5 min-w-0">
        <span className={`relative flex items-center justify-center w-2 h-2 shrink-0`}>
          <span className={`absolute inset-0 rounded-full opacity-60 ${accentDot[accent]} ${accentGlow[accent]}`} />
          <span className={`absolute inset-0 rounded-full opacity-30 ${accentDot[accent]} animate-ping`}
            style={{ animationDuration: '3s', animationDelay: '1s' }}
          />
          <span className={`w-2 h-2 rounded-full relative z-10 ${accentDot[accent]}`} />
        </span>
        <div className="min-w-0">
          <h2 className={[titleSize[size], 'font-semibold tracking-tight text-primary truncate'].join(' ')}>{title}</h2>
          {subtitle && <p className="text-[10px] text-tertiary font-mono truncate mt-0.5 tracking-wide">{subtitle}</p>}
        </div>
      </div>
      {meta != null && <div className="shrink-0">{meta}</div>}
    </div>
  )
}
