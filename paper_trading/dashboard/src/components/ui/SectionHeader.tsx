import type { ReactNode } from 'react'

interface SectionHeaderProps {
  title: string
  subtitle?: string
  /** Kept for API stability; visually collapses to a single static dot. */
  accent?: 'emerald' | 'blue' | 'purple' | 'amber' | 'indigo' | 'pink' | 'neutral'
  meta?: ReactNode
  className?: string
  border?: boolean
}

const accentDot: Record<NonNullable<SectionHeaderProps['accent']>, string> = {
  emerald: 'bg-accent-emerald',
  blue: 'bg-accent-blue',
  purple: 'bg-accent-purple',
  amber: 'bg-accent-amber',
  indigo: 'bg-accent-indigo',
  pink: 'bg-accent-pink',
  neutral: 'bg-signal-init/60',
}

/** Section heading with accent dot, optional subtitle, and meta slot for actions/buttons. */
export default function SectionHeader({
  title,
  subtitle,
  accent = 'emerald',
  meta,
  className = '',
  border = false,
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
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${accentDot[accent]}`} />
        <div className="min-w-0">
          <h2 className="text-sm font-semibold tracking-tight text-primary truncate">{title}</h2>
          {subtitle && <p className="text-[10px] text-tertiary font-mono truncate mt-0.5 tracking-wide">{subtitle}</p>}
        </div>
      </div>
      {meta != null && <div className="shrink-0">{meta}</div>}
    </div>
  )
}
