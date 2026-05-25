import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

interface TrendIndicatorProps {
  value: number
  suffix?: string
  precision?: number
  size?: 'sm' | 'md' | 'lg'
  colored?: boolean
  className?: string
}

const sizeMap = {
  sm: { icon: 'w-2.5 h-2.5', text: 'text-[10px]' },
  md: { icon: 'w-3 h-3', text: 'text-xs' },
  lg: { icon: 'w-3.5 h-3.5', text: 'text-sm' },
}

export default function TrendIndicator({
  value, suffix = '%', precision = 2, size = 'md', colored = true, className = '',
}: TrendIndicatorProps) {
  const s = sizeMap[size]
  const isPos = value > 0
  const isNeg = value < 0
  const color = colored
    ? (isPos ? 'text-gov-green' : isNeg ? 'text-gov-red' : 'text-tertiary')
    : 'text-secondary'

  if (value === 0) {
    return (
      <span className={`inline-flex items-center gap-1 font-mono tabular-nums ${color} ${s.text} ${className}`}>
        <Minus className={s.icon} strokeWidth={2} />
        0.00{suffix}
      </span>
    )
  }

  const Icon = isPos ? TrendingUp : TrendingDown
  return (
    <span className={`inline-flex items-center gap-1 font-mono tabular-nums ${color} ${s.text} ${className}`}>
      <Icon className={s.icon} strokeWidth={2} />
      {isPos ? '+' : ''}{value.toFixed(precision)}{suffix}
    </span>
  )
}
