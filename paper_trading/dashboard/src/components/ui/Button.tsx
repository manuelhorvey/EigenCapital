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
    'bg-accent-emerald/90 text-[#08090c] hover:bg-accent-emerald focus-visible:shadow-[0_0_0_2px_rgba(45,211,191,0.5)] active:scale-[0.98]',
  secondary:
    'bg-panel border border-default text-secondary hover:bg-panel-hover hover:text-primary hover:border-strong focus-visible:shadow-[0_0_0_1px_rgba(45,211,191,0.3)] active:scale-[0.98]',
  ghost:
    'border border-transparent text-secondary hover:text-primary hover:bg-panel hover:border-default focus-visible:shadow-[0_0_0_1px_rgba(45,211,191,0.3)] active:scale-[0.98]',
  outline:
    'border border-accent-emerald/50 text-accent-emerald hover:bg-accent-emerald/10 hover:border-accent-emerald focus-visible:shadow-[0_0_0_2px_rgba(45,211,191,0.3)] active:scale-[0.98]',
  danger:
    'bg-gov-red/90 text-white hover:bg-gov-red focus-visible:shadow-[0_0_0_2px_rgba(239,68,68,0.5)] active:scale-[0.98]',
}

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'text-2xs px-2 py-1 gap-1',
  md: 'text-xs px-3 py-1.5 gap-1.5',
  lg: 'text-sm px-4 py-2 gap-2',
}

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
      className={`inline-flex items-center justify-center rounded font-medium transition-all duration-150 outline-none disabled:opacity-40 disabled:pointer-events-none ${variantStyles[variant]} ${sizeStyles[size]} ${className}`}
      {...props}
    >
      {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" strokeWidth={2} /> : icon}
      {children && <span>{children}</span>}
    </button>
  )
}
