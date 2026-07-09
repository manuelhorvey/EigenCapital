import { ChevronDown } from 'lucide-react'

interface SelectOption {
  value: string
  label: string
}

interface SelectProps {
  options: SelectOption[]
  value: string
  onChange: (value: string) => void
  placeholder?: string
  size?: 'sm' | 'md'
  className?: string
}

const sizeStyles = {
  sm: 'text-2xs py-1 pl-2 pr-6',
  md: 'text-xs py-1.5 pl-2.5 pr-7',
}

/** Styled dropdown select with chevron icon and size variants. */
export default function Select({
  options,
  value,
  onChange,
  placeholder = 'All',
  size = 'sm',
  className = '',
}: SelectProps) {
  return (
    <div className={`relative ${className}`}>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className={`appearance-none w-full bg-surface border border-default rounded text-primary font-medium transition-colors duration-150 hover:border-strong focus:outline-none focus:border-strong focus:shadow-[0_0_0_1px_rgba(45,211,191,0.2)] focus-ring ${sizeStyles[size]}`}
      >
        <option value="">{placeholder}</option>
        {options.map(opt => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
      <ChevronDown className="absolute right-1.5 top-1/2 -translate-y-1/2 w-3 h-3 text-muted pointer-events-none" strokeWidth={2} />
    </div>
  )
}
