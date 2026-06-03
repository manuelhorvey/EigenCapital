import { useState } from 'react'
import { X } from 'lucide-react'
import Select from './ui/Select'
import Badge from './ui/Badge'

export interface FilterState {
  archetype: string
  regime: string
  asset: string
}

interface FilterBarProps {
  assets: string[]
  archetypes?: string[]
  regimes?: string[]
  onChange: (filters: FilterState) => void
}

const DEFAULT_FILTER: FilterState = { archetype: '', regime: '', asset: '' }

const ARCHETYPES = ['BREAKOUT', 'MEAN_REVERSION', 'MOMENTUM', 'VOL_EXPANSION']
const REGIMES = ['GREEN', 'YELLOW', 'RED']

export default function FilterBar({ assets, archetypes = ARCHETYPES, regimes = REGIMES, onChange }: FilterBarProps) {
  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTER)

  function update(key: keyof FilterState, value: string) {
    const next = { ...filters, [key]: value }
    setFilters(next)
    onChange(next)
  }

  const activeCount = Object.values(filters).filter(Boolean).length

  return (
    <div className="flex flex-wrap items-center gap-2 py-2 px-3 bg-panel rounded-lg border border-default">
      <span className="text-2xs font-medium text-tertiary uppercase tracking-wider mr-1">Filters</span>

      <Select
        options={assets.map(a => ({ value: a, label: a }))}
        value={filters.asset}
        onChange={v => update('asset', v)}
        placeholder="All Assets"
      />

      <Select
        options={archetypes.map(a => ({ value: a, label: a }))}
        value={filters.archetype}
        onChange={v => update('archetype', v)}
        placeholder="All Archetypes"
      />

      <Select
        options={regimes.map(r => ({ value: r, label: r }))}
        value={filters.regime}
        onChange={v => update('regime', v)}
        placeholder="All Regimes"
      />

      {activeCount > 0 && (
        <>
          <span className="text-2xs text-muted">|</span>
          <button
            onClick={() => {
              setFilters(DEFAULT_FILTER)
              onChange(DEFAULT_FILTER)
            }}
            className="text-2xs text-tertiary hover:text-primary transition-colors"
          >
            Clear {activeCount > 1 ? `(${activeCount})` : ''}
          </button>
        </>
      )}
    </div>
  )
}
