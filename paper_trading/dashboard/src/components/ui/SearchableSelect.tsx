import { useState, useRef, useEffect, useMemo } from 'react'
import { Search, ChevronDown } from 'lucide-react'

interface SelectOption {
  value: string
  label: string
}

interface SearchableSelectProps {
  options: SelectOption[]
  value: string
  onChange: (value: string) => void
  placeholder?: string
  size?: 'sm' | 'md'
  className?: string
  searchPlaceholder?: string
}

const sizeStyles = {
  sm: 'text-2xs',
  md: 'text-xs',
}

const inputSizeStyles = {
  sm: 'py-1 pl-7 pr-2 text-2xs',
  md: 'py-1.5 pl-8 pr-2.5 text-xs',
}

/**
 * Searchable dropdown select with filter input — replaces the basic Select component where filtering is needed (C2).
 *
 * Usage:
 *   <SearchableSelect
 *     options={archetypes.map(a => ({ value: a, label: a }))}
 *     value={archetypeFilter}
 *     onChange={setArchetypeFilter}
 *     placeholder="All Archetypes"
 *   />
 *
 * @param options - Array of { value, label }
 * @param value - Currently selected value (empty string for "All")
 * @param onChange - Callback when selection changes
 * @param placeholder - Text shown when no value selected
 * @param searchPlaceholder - Placeholder for the search input
 */
export default function SearchableSelect({
  options,
  value,
  onChange,
  placeholder = 'All',
  size = 'sm',
  className = '',
  searchPlaceholder = 'Type to filter…',
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const ref = useRef<HTMLDivElement>(null)

  const filtered = useMemo(
    () =>
      search
        ? options.filter(o => o.label.toLowerCase().includes(search.toLowerCase()))
        : options,
    [options, search],
  )

  useEffect(() => {
    if (!open) {
      setSearch('') // Reset search on close
    }
  }, [open])

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const selectedLabel = options.find(o => o.value === value)?.label ?? placeholder

  return (
    <div className={`relative ${className}`} ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`appearance-none w-full bg-surface border border-default rounded text-primary font-medium transition-colors duration-150 hover:border-strong focus:outline-none focus:border-strong focus:shadow-[0_0_0_1px_rgba(45,211,191,0.2)] focus-ring flex items-center justify-between ${sizeStyles[size]} py-1 pl-2 pr-1.5 min-w-[100px]`}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className={value ? 'text-primary' : 'text-tertiary'}>{selectedLabel}</span>
        <ChevronDown className={`w-3 h-3 text-muted transition-transform duration-150 ${open ? 'rotate-180' : ''}`} strokeWidth={2} />
      </button>

      {open && (
        <div className="absolute top-full mt-1 left-0 right-0 z-50 bg-surface border border-default rounded shadow-card max-h-56 flex flex-col">
          {/* Search input */}
          <div className="relative p-1.5 border-b border-default">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3 h-3 text-muted pointer-events-none" strokeWidth={2} />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={searchPlaceholder}
              className={`w-full bg-panel border border-default rounded text-primary placeholder:text-muted focus:outline-none focus:border-strong ${inputSizeStyles[size]}`}
              autoFocus
            />
          </div>

          {/* Options list */}
          <div className="overflow-y-auto flex-1" role="listbox">
            <button
              role="option"
              aria-selected={value === ''}
              onClick={() => { onChange(''); setOpen(false) }}
              className={`w-full text-left px-2 py-1.5 ${sizeStyles[size]} transition-colors hover:bg-panel ${
                value === '' ? 'text-primary bg-panel/60 font-semibold' : 'text-tertiary'
              }`}
            >
              {placeholder}
            </button>
            {filtered.map(opt => (
              <button
                key={opt.value}
                role="option"
                aria-selected={value === opt.value}
                onClick={() => { onChange(opt.value); setOpen(false) }}
                className={`w-full text-left px-2 py-1.5 ${sizeStyles[size]} transition-colors hover:bg-panel ${
                  value === opt.value ? 'text-primary bg-panel/60 font-semibold' : 'text-tertiary'
                }`}
              >
                {opt.label}
              </button>
            ))}
            {filtered.length === 0 && (
              <div className="px-2 py-4 text-2xs text-tertiary text-center">No matches</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
