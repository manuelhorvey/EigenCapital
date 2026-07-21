import type { ReactNode } from 'react'
import { ArrowUp, ArrowDown, Minus } from 'lucide-react'

export type BadgeVariant = 'default' | 'success' | 'warning' | 'error' | 'neutral'

interface BadgeProps {
  variant?: BadgeVariant
  size?: 'sm' | 'md'
  dot?: boolean
  glow?: boolean
  icon?: 'long' | 'short' | 'flat' | ReactNode
  children: ReactNode
  className?: string
}

const variantStyles: Record<BadgeVariant, string> = {
  default: 'bg-accent-emerald/10 text-accent-emerald border-accent-emerald/25',
  success: 'bg-signal-long-muted text-signal-long border-signal-long/35',
  warning: 'bg-signal-warn-muted text-signal-warn border-signal-warn/35',
  error: 'bg-signal-short-muted text-signal-short border-signal-short/35',
  neutral: 'bg-signal-init-muted text-signal-init border-signal-init/35',
}

const sizeStyles = {
  sm: 'text-[10px] px-1.5 py-0.5',
  md: 'text-[11px] px-2 py-0.5',
}

function BadgeIcon({ icon }: { icon: NonNullable<BadgeProps['icon']> }) {
  if (icon === 'long') return <ArrowUp className="w-2.5 h-2.5" strokeWidth={2.5} />
  if (icon === 'short') return <ArrowDown className="w-2.5 h-2.5" strokeWidth={2.5} />
  if (icon === 'flat') return <Minus className="w-2.5 h-2.5" strokeWidth={2.5} />
  return <>{icon}</>
}

/** Colored badge/tag for displaying signal status, direction, or governance state. @param variant - color scheme; @param size - sm or md; @param dot - small dot indicator; @param glow - outer glow effect; @param icon - direction arrow ('long'/'short'/'flat') or custom node. */
export default function Badge({
  variant = 'default',
  size = 'sm',
  dot = false,
  glow = false,
  icon,
  children,
  className = '',
}: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded font-semibold tracking-wider uppercase border ${variantStyles[variant]} ${sizeStyles[size]} relative ${className}`}
    >
      {glow && (
        <span className="absolute inset-0 rounded pointer-events-none opacity-20" style={{ boxShadow: '0 0 6px 1px currentColor' }} />
      )}
      {dot && <span className="w-1 h-1 rounded-full bg-current shrink-0" />}
      {icon && <BadgeIcon icon={icon} />}
      {children}
    </span>
  )
}

export function signalToBadge(signal: string): { variant: BadgeVariant; icon: BadgeProps['icon'] } {
  if (signal === 'BUY' || signal === 'LONG' || signal === 'TP') {
    return { variant: 'success', icon: 'long' }
  }
  if (signal === 'SELL' || signal === 'SHORT' || signal === 'SL') {
    return { variant: 'error', icon: 'short' }
  }
  return { variant: 'warning', icon: 'flat' }
}

export function reasonToBadge(reason?: string | null): BadgeVariant {
  const r = reason?.toLowerCase() ?? ''
  if (r === 'tp' || r === 'tp_hit' || r === 'trailing_sl') return 'success'
  if (r === 'sl' || r === 'sl_hit' || r === 'stop_loss') return 'error'
  if (r === 'signal_flip' || r === 'flip') return 'warning'
  return 'neutral'
}
