import type { ReactNode } from 'react'
import { ArrowUp, ArrowDown, Minus } from 'lucide-react'

type BadgeVariant = 'default' | 'success' | 'warning' | 'error' | 'neutral'

interface BadgeProps {
  variant?: BadgeVariant
  size?: 'sm' | 'md'
  dot?: boolean
  icon?: 'long' | 'short' | 'flat' | ReactNode
  children: ReactNode
  className?: string
}

const variantStyles: Record<BadgeVariant, string> = {
  default: 'bg-accent-emerald/10 text-accent-emerald border-accent-emerald/20',
  success: 'bg-gov-green-muted text-gov-green border-gov-green/25',
  warning: 'bg-gov-yellow-muted text-gov-yellow border-gov-yellow/25',
  error: 'bg-gov-red-muted text-gov-red border-gov-red/25',
  neutral: 'bg-gov-init-muted text-gov-init border-gov-init/25',
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

export default function Badge({
  variant = 'default',
  size = 'sm',
  dot = false,
  icon,
  children,
  className = '',
}: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded font-semibold tracking-wider uppercase border ${variantStyles[variant]} ${sizeStyles[size]} ${className}`}
    >
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

export function reasonToBadge(reason?: string): BadgeVariant {
  const r = reason?.toLowerCase() ?? ''
  if (r === 'tp' || r === 'tp_hit') return 'success'
  if (r === 'sl' || r === 'sl_hit' || r === 'stop_loss') return 'error'
  if (r === 'signal_flip' || r === 'flip') return 'warning'
  return 'neutral'
}
