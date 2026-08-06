import { useId } from 'react'
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
  /** Visible label, rendered as a sr-only control label for screen readers. */
  label?: string
  className?: string
}

const sizeStyles = {
  sm: 'text-2xs py-1 pl-2 pr-6',
  md: 'text-xs py-1.5 pl-2.5 pr-7',
}

export default function Select({
  options,
  value,
  onChange,
  placeholder = 'All',
  size = 'sm',
  label,
  className = '',
}: SelectProps) {
  const id = `select-${useId()}`
  return (
    <div className={`relative ${className}`}>
      {label && <label htmlFor={id} className="sr-only">{label}</label>}
      <select
        id={label ? id : undefined}
        aria-label={label ? undefined : placeholder || 'Select option'}
        value={value}
        onChange={e => onChange(e.target.value)}
        className={`appearance-none w-full bg-surface border border-default rounded text-primary font-medium transition-colors duration-150 hover:border-strong focus:outline-none focus:border-strong focus:shadow-[0_0_0_1px_rgba(255,176,32,0.25)] ${sizeStyles[size]}`}
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
