import { useState } from 'react'

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

const ARCHETYPES = ['', 'BREAKOUT', 'MEAN_REVERSION', 'MOMENTUM', 'VOL_EXPANSION']
const REGIMES = ['', 'GREEN', 'YELLOW', 'RED']

export default function FilterBar({ assets, archetypes = ARCHETYPES, regimes = REGIMES, onChange }: FilterBarProps) {
  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTER)

  function update(key: keyof FilterState, value: string) {
    const next = { ...filters, [key]: value }
    setFilters(next)
    onChange(next)
  }

  return (
    <div className="flex flex-wrap items-center gap-2 py-2 px-3 bg-panel rounded-lg border border-default">
      <span className="text-2xs font-medium text-tertiary uppercase tracking-wider mr-1">Filters</span>

      <select
        value={filters.asset}
        onChange={e => update('asset', e.target.value)}
        className="filter-select"
      >
        <option value="">All Assets</option>
        {assets.map(a => <option key={a} value={a}>{a}</option>)}
      </select>

      <select
        value={filters.archetype}
        onChange={e => update('archetype', e.target.value)}
        className="filter-select"
      >
        <option value="">All Archetypes</option>
        {archetypes.filter(Boolean).map(a => <option key={a} value={a}>{a}</option>)}
      </select>

      <select
        value={filters.regime}
        onChange={e => update('regime', e.target.value)}
        className="filter-select"
      >
        <option value="">All Regimes</option>
        {regimes.filter(Boolean).map(r => <option key={r} value={r}>{r}</option>)}
      </select>

      {filters.archetype && (
        <button onClick={() => update('archetype', '')} className="text-2xs text-gov-red hover:underline">✕</button>
      )}
      {filters.regime && (
        <button onClick={() => update('regime', '')} className="text-2xs text-gov-red hover:underline">✕</button>
      )}
    </div>
  )
}
