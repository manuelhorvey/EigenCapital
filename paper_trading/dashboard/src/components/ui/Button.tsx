import type { ReactNode, ButtonHTMLAttributes } from 'react'
import { Loader2 } from 'lucide-react'

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'outline' | 'danger'
type ButtonSize = 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  icon?: ReactNode
  children?: ReactNode
}

const variantStyles: Record<ButtonVariant, string> = {
  primary:
    'bg-accent-emerald text-[--color-app] hover:brightness-110 active:scale-[0.98]',
  secondary:
    'bg-panel border border-default text-secondary hover:bg-panel-hover hover:text-primary hover:border-strong active:scale-[0.98]',
  ghost:
    'border border-transparent text-secondary hover:text-primary hover:bg-panel hover:border-default active:scale-[0.98]',
  outline:
    'border border-accent-emerald/50 text-accent-emerald hover:bg-accent-emerald/10 hover:border-accent-emerald active:scale-[0.98]',
  danger:
    'bg-signal-short text-white hover:brightness-110 active:scale-[0.98]',
}

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'text-2xs px-2 py-1 gap-1',
  md: 'text-xs px-3 py-1.5 gap-1.5',
  lg: 'text-sm px-4 py-2 gap-2',
}

/** Styled action button with variant, size, loading spinner, and optional icon slot. */
export default function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  icon,
  children,
  disabled,
  className = '',
  ...props
}: ButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center rounded font-medium transition-all duration-150 focus-ring disabled:opacity-40 disabled:pointer-events-none ${variantStyles[variant]} ${sizeStyles[size]} ${className}`}
      {...props}
    >
      {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" strokeWidth={2} /> : icon}
      {children && <span>{children}</span>}
    </button>
  )
}
