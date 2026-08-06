import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Search, ArrowUpRight, CornerDownLeft } from 'lucide-react'
import { useCommandPalette } from '../hooks/useCommandPalette'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import { useSelectedAsset } from '../hooks/useSelectedAsset'
import { useToast } from './toast/Toast'
import useFocusTrap from '../hooks/useFocusTrap'
import { NAV_ITEMS } from '../lib/navigation'

interface PaletteItem {
  id: string
  group: string
  label: string
  hint?: string
  keywords?: string
  icon: React.ReactNode
  action: () => void
}

// Anchor sections per route (mirrors the `id` attrs in each workspace)
const SECTIONS: Record<string, { id: string; label: string }[]> = {
  '/trading': [
    { id: 'signals', label: 'Signals & Equity' },
  ],
  '/trades': [
    { id: 'trades-outcomes', label: 'Trade Outcomes' },
    { id: 'trade-log', label: 'Trade Log' },
    { id: 'execution-feed', label: 'Execution Feed' },
  ],
  '/execution': [
    { id: 'optimization', label: 'Optimization Drift' },
    { id: 'execution-quality', label: 'Execution Quality' },
    { id: 'trade-attribution', label: 'Trade Attribution' },
  ],
  '/risk': [
    { id: 'pek', label: 'PEK State' },
    { id: 'admission', label: 'PEK Admission' },
    { id: 'portfolio-risk', label: 'Portfolio Risk' },
    { id: 'governance', label: 'Governance Constraints' },
    { id: 'halt-gates', label: 'Halt Gates' },
    { id: 'health-scores', label: 'Health Scores' },
  ],
  '/monitor': [
    { id: 'system', label: 'System Health' },
    { id: 'alerts', label: 'Active Alerts' },
    { id: 'governance', label: 'Governance Health' },
    { id: 'lead', label: 'Lead Indicators' },
  ],
  '/analytics': [
    { id: 'statistics', label: 'Statistical Metrics' },
    { id: 'calibration', label: 'Calibration' },
  ],
}

function normalize(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '')
}

export default function CommandPalette() {
  const { isOpen, close } = useCommandPalette()
  const navigate = useNavigate()
  const location = useLocation()
  const { setSelectedAsset } = useSelectedAsset()
  const { toast } = useToast()
  const trapRef = useFocusTrap()
  const inputRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const [activeIdx, setActiveIdx] = useState(0)
  const listRef = useRef<HTMLDivElement>(null)
  const { data: assets } = useSystemSnapshot(systemSelectors.assets)

  const path = location.pathname

  const items = useMemo<PaletteItem[]>(() => {
    const result: PaletteItem[] = []

    for (const p of NAV_ITEMS) {
      const Icon = p.icon
      result.push({
        id: `page-${p.to}`,
        group: 'Pages',
        label: p.label,
        hint: p.desc,
        keywords: p.desc,
        icon: <Icon className="w-3.5 h-3.5" strokeWidth={1.75} />,
        action: () => {
          navigate(p.to)
          window.scrollTo({ top: 0 })
        },
      })
    }

    for (const [route, sections] of Object.entries(SECTIONS)) {
      for (const s of sections) {
        result.push({
          id: `section-${route}-${s.id}`,
          group: 'Sections',
          label: s.label,
          hint: route === path ? 'Jump to section' : `Go to ${route.replace('/', '')} → ${s.label}`,
          keywords: `${route} ${s.label}`,
          icon: <ArrowUpRight className="w-3.5 h-3.5" strokeWidth={1.75} />,
          action: () => {
            const go = () => {
              requestAnimationFrame(() => {
                document.getElementById(s.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                const el = document.getElementById(s.id)
                const focusTarget = el?.querySelector<HTMLElement>('h2, h3, [tabindex="0"]')
                focusTarget?.focus({ preventScroll: true })
              })
            }
            if (route === path) {
              go()
            } else {
              navigate(route)
              setTimeout(go, 120)
            }
          },
        })
      }
    }

    if (assets) {
      for (const [name, asset] of Object.entries(assets)) {
        const signal = asset.final_signal ?? 'FLAT'
        result.push({
          id: `asset-${name}`,
          group: 'Assets',
          label: name,
          hint: `Signal ${signal} · ${asset.metrics?.current_price != null ? `$${asset.metrics.current_price}` : '—'}`,
          keywords: `${name} ${signal} asset pair`,
          icon: <Search className="w-3.5 h-3.5" strokeWidth={1.75} />,
          action: () => setSelectedAsset(name),
        })
      }
    }

    return result
  }, [assets, navigate, path, setSelectedAsset])

  const filtered = useMemo(() => {
    const q = normalize(query)
    if (!q) return items
    return items.filter(i => normalize(i.label).includes(q) || normalize(i.keywords ?? '').includes(q))
  }, [items, query])

  useEffect(() => {
    if (isOpen) {
      setQuery('')
      setActiveIdx(0)
      // Focus the input after the dialog mounts
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [isOpen])

  // Reset active index when the list changes size
  useEffect(() => {
    setActiveIdx(0)
  }, [query, isOpen])

  // Keep active item scrolled into view
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${activeIdx}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  }, [activeIdx])

  useEffect(() => {
    if (!isOpen) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setActiveIdx(i => Math.min(i + 1, Math.max(0, filtered.length - 1)))
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setActiveIdx(i => Math.max(i - 1, 0))
      }
      if (e.key === 'Enter') {
        e.preventDefault()
        const item = filtered[activeIdx]
        if (item) {
          item.action()
          close()
        }
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [isOpen, filtered, activeIdx, close])

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-[90] flex items-start justify-center pt-[12vh] px-4">
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" onClick={close} aria-hidden="true" />

      {/* Dialog */}
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="relative w-full max-w-lg rounded-xl bg-app border border-default shadow-modal overflow-hidden animate-scale-in"
      >
        <div className="flex items-center gap-2.5 px-3.5 py-3 border-b border-default">
          <Search className="w-4 h-4 text-tertiary shrink-0" strokeWidth={2} />
          <input
            ref={inputRef}
            id="command-palette-input"
            name="command-palette-query"
            type="text"
            role="combobox"
            aria-expanded={filtered.length > 0}
            aria-controls="cp-listbox"
            aria-autocomplete="list"
            aria-activedescendant={filtered[activeIdx] ? `cp-option-${filtered[activeIdx].id}` : undefined}
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search pages, assets, sections…"
            aria-label="Search pages, assets, and sections"
            autoComplete="off"
            spellCheck={false}
            className="flex-1 min-w-0 bg-transparent text-sm text-primary placeholder:text-muted outline-none"
          />
          <kbd className="hidden sm:inline-flex items-center px-1.5 py-0.5 rounded border border-default text-[9px] font-mono text-tertiary bg-panel/50">
            ESC
          </kbd>
        </div>

        <div ref={listRef} id="cp-listbox" className="max-h-[45vh] overflow-y-auto py-1.5 overscroll-contain" role="listbox" aria-label="Results">
          {/* Visually-hidden active description for screen readers */}
          <span className="sr-only" aria-live="polite">
            {filtered[activeIdx] ? `${filtered[activeIdx].label}, ${filtered[activeIdx].group}` : ''}
          </span>
          {filtered.length === 0 ? (
            <div className="px-4 py-8 text-center">
              <p className="text-xs text-tertiary">No results for “{query}”</p>
              <p className="text-[10px] text-muted mt-1">Try an asset ticker (e.g. EURUSD), a page, or a section name.</p>
            </div>
          ) : (
            (() => {
              const groups: { name: string; start: number; end: number }[] = []
              let last = ''
              filtered.forEach((item, i) => {
                if (item.group !== last) {
                  groups.push({ name: item.group, start: i, end: i })
                  last = item.group
                } else {
                  groups[groups.length - 1].end = i
                }
              })
              return groups.map(g => (
                <div key={g.name} role="group" aria-label={g.name}>
                  <p className="px-3.5 pt-2 pb-1 text-[9px] font-semibold uppercase tracking-widest text-tertiary/70">
                    {g.name}
                  </p>
                  {filtered.slice(g.start, g.end + 1).map((item, offset) => {
                    const idx = g.start + offset
                    const active = idx === activeIdx
                    return (
                      <button
                        key={item.id}
                        id={`cp-option-${item.id}`}
                        type="button"
                        role="option"
                        aria-selected={active}
                        data-idx={idx}
                        // Options stay out of the tab order: keyboard users
                        // navigate with arrow keys + Enter (managed via the
                        // combobox input's aria-activedescendant), mouse users click.
                        tabIndex={-1}
                        onMouseEnter={() => setActiveIdx(idx)}
                        onClick={() => {
                          item.action()
                          close()
                        }}
                        className={`w-full flex items-center gap-2.5 px-3.5 py-2 text-left transition-colors ${
                          active ? 'bg-accent-emerald/10 text-primary' : 'text-secondary'
                        }`}
                      >
                        <span className={`shrink-0 ${active ? 'text-accent-emerald' : 'text-tertiary'}`}>{item.icon}</span>
                        <span className="flex-1 min-w-0">
                          <span className="block text-xs font-medium truncate">{item.label}</span>
                          <span className="block text-[10px] text-tertiary truncate">{item.hint}</span>
                        </span>
                        {active && (
                          <span className="shrink-0 text-tertiary">
                            <CornerDownLeft className="w-3 h-3" strokeWidth={2} />
                          </span>
                        )}
                      </button>
                    )
                  })}
                </div>
              ))
            })()
          )}
        </div>

        <div className="flex items-center justify-between px-3.5 py-2 border-t border-default bg-surface/40">
          <p className="text-[9px] text-tertiary font-mono">
            <kbd className="text-tertiary">↑↓</kbd> navigate · <kbd className="text-tertiary">↵</kbd> open
          </p>
          <button
            type="button"
            onClick={() => {
              const first = filtered[0]
              if (first) {
                first.action()
                close()
              } else {
                toast({ title: 'No matching command', variant: 'info' })
              }
            }}
            className="text-[9px] text-tertiary hover:text-primary transition-colors focus-ring rounded px-1"
          >
            Open first result
          </button>
        </div>
      </div>
    </div>
  )
}
