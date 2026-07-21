import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Search, LayoutDashboard, Zap, BarChart3, Shield, Activity,
  RefreshCw, Download, AlertTriangle, Settings, FileText,
  Ban, CheckCircle, Terminal, Clock, Star,
} from 'lucide-react'
import { useDataExport } from '../hooks/useDataExport'

// ── Types ────────────────────────────────────────────────────────

interface CommandItem {
  id: string
  label: string
  description: string
  icon: React.ReactNode
  action: () => void
  keywords: string[]
  section: 'navigation' | 'actions' | 'assets' | 'signals'
}

interface AssetSignal {
  signal?: string
  confidence?: number
  price?: number
  position?: { side?: string; entry?: number }
}

interface CommandPaletteProps {
  assetNames?: string[]
  onSelectAsset?: (name: string) => void
  assets?: Record<string, AssetSignal>
}

// ── Recent items tracking (localStorage-backed) ─────────────────
const RECENT_KEY = 'ec_cmd_palette_recent'
const MAX_RECENT = 5

function loadRecent(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function saveRecent(ids: string[]) {
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(ids.slice(0, MAX_RECENT))) } catch {}
}

function recordUsage(id: string) {
  const recent = loadRecent()
  const updated = [id, ...recent.filter(r => r !== id)].slice(0, MAX_RECENT)
  saveRecent(updated)
}

// ── Section config ───────────────────────────────────────────────

interface SectionDef {
  id: string
  label: string
  icon: React.ReactNode
}

const SECTIONS: Record<string, SectionDef> = {
  navigation: { id: 'navigation', label: 'Navigation', icon: <LayoutDashboard className="w-3 h-3" strokeWidth={1.5} /> },
  actions: { id: 'actions', label: 'Actions', icon: <Terminal className="w-3 h-3" strokeWidth={1.5} /> },
  assets: { id: 'assets', label: 'Assets', icon: <Activity className="w-3 h-3" strokeWidth={1.5} /> },
  signals: { id: 'signals', label: 'Active Signals', icon: <Zap className="w-3 h-3" strokeWidth={1.5} /> },
}

const SECTION_ORDER: (keyof typeof SECTIONS)[] = ['navigation', 'actions', 'assets', 'signals']

/** Cmd+K command palette v2 — section groups, recent items, vim-style j/k nav. */
export default function CommandPalette({ assetNames = [], onSelectAsset, assets = {} }: CommandPaletteProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [recentIds] = useState<string[]>(() => loadRecent())
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const { exportJson } = useDataExport()

  // Toggle on Cmd+K / Ctrl+K. Also / to open when not in input.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setOpen(prev => !prev)
      }
      if (e.key === '/' && !open && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName ?? '')) {
        e.preventDefault()
        setOpen(true)
      }
      if (e.key === 'Escape' && open) {
        e.preventDefault()
        setOpen(false)
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open])

  // Focus input on open
  useEffect(() => {
    if (open) {
      setQuery('')
      setSelectedIndex(0)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open])

  // Build command list with sections
  const commands = useMemo<CommandItem[]>(() => {
    const items: CommandItem[] = [
      // ── Navigation ────────────────────────────
      { id: 'nav-dashboard', label: 'Dashboard', description: 'Overview, equity, positions', icon: <LayoutDashboard className="w-3.5 h-3.5" strokeWidth={1.5} />, action: () => navigate('/'), keywords: ['dashboard', 'home', 'overview', 'equity'], section: 'navigation' },
      { id: 'nav-trading', label: 'Trading', description: 'Signals, fills, open trades', icon: <Zap className="w-3.5 h-3.5" strokeWidth={1.5} />, action: () => navigate('/trading'), keywords: ['trading', 'signals', 'trades'], section: 'navigation' },
      { id: 'nav-analytics', label: 'Analytics', description: 'Performance attribution, execution quality', icon: <BarChart3 className="w-3.5 h-3.5" strokeWidth={1.5} />, action: () => navigate('/analytics'), keywords: ['analytics', 'attribution', 'execution'], section: 'navigation' },
      { id: 'nav-risk', label: 'Governance & Risk', description: 'Health scores, governance, constraints', icon: <Shield className="w-3.5 h-3.5" strokeWidth={1.5} />, action: () => navigate('/risk'), keywords: ['risk', 'governance', 'health'], section: 'navigation' },
      { id: 'nav-reports', label: 'Reports', description: 'Download reports, audit log', icon: <FileText className="w-3.5 h-3.5" strokeWidth={1.5} />, action: () => navigate('/reports'), keywords: ['reports', 'audit', 'export'], section: 'navigation' },
      { id: 'nav-settings', label: 'Settings', description: 'Preferences, theme, API keys', icon: <Settings className="w-3.5 h-3.5" strokeWidth={1.5} />, action: () => navigate('/settings'), keywords: ['settings', 'preferences', 'theme'], section: 'navigation' },

      // ── Actions ───────────────────────────────
      { id: 'action-refresh', label: 'Refresh Dashboard', description: 'Force refresh all dashboard data', icon: <RefreshCw className="w-3.5 h-3.5" strokeWidth={1.5} />, action: () => { window.location.reload() }, keywords: ['refresh', 'reload', 'update', 'sync'], section: 'actions' },
      { id: 'action-export', label: 'Export Data', description: 'Download portfolio state as JSON', icon: <Download className="w-3.5 h-3.5" strokeWidth={1.5} />, action: () => exportJson('/state-bundle.json', { filename: `eigencapital-snapshot-${Date.now()}` }), keywords: ['export', 'download', 'json', 'backup'], section: 'actions' },
      { id: 'action-alerts', label: 'View Alerts', description: 'View all active system alerts', icon: <AlertTriangle className="w-3.5 h-3.5" strokeWidth={1.5} />, action: () => navigate('/risk'), keywords: ['alert', 'critical', 'error', 'warning'], section: 'actions' },
      { id: 'action-halt-engine', label: 'Halt Engine', description: 'Emergency halt all trading activity', icon: <Ban className="w-3.5 h-3.5" strokeWidth={1.5} />, action: () => { if (window.confirm('Halt the engine?')) { fetch('/api/engine/halt', { method: 'POST' }).catch(() => {}) } }, keywords: ['halt', 'emergency', 'stop', 'engine', 'kill', 'panic'], section: 'actions' },
      { id: 'action-acknowledge-weekly', label: 'Acknowledge Weekly Review', description: 'Acknowledge current weekly review', icon: <CheckCircle className="w-3.5 h-3.5" strokeWidth={1.5} />, action: () => { fetch('/weekly-review/acknowledge', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => {}) }, keywords: ['acknowledge', 'weekly', 'review', 'confirm'], section: 'actions' },
      { id: 'action-clear-cache', label: 'Clear Cache', description: 'Clear server-side API cache', icon: <Terminal className="w-3.5 h-3.5" strokeWidth={1.5} />, action: () => { fetch('/api/clear-cache', { method: 'POST' }).catch(() => {}) }, keywords: ['cache', 'clear', 'refresh', 'api'], section: 'actions' },

      // ── Shortcuts display ─────────────────────
      { id: 'action-shortcuts', label: 'Keyboard Shortcuts', description: 'View all available keyboard shortcuts', icon: <Star className="w-3.5 h-3.5" strokeWidth={1.5} />, action: () => { window.dispatchEvent(new KeyboardEvent('keydown', { key: '?', bubbles: true })) }, keywords: ['shortcut', 'keyboard', 'hotkey', 'keys'], section: 'actions' },
    ]

    // Add asset search items
    for (const name of assetNames) {
      items.push({
        id: `asset-${name}`,
        label: name,
        description: 'Open asset detail panel',
        icon: <Activity className="w-3.5 h-3.5" strokeWidth={1.5} />,
        action: () => { onSelectAsset?.(name); recordUsage(`asset-${name}`) },
        keywords: [name.toLowerCase(), 'asset', 'position'],
        section: 'assets',
      })
    }

    // Add signal search items
    for (const [name, asset] of Object.entries(assets)) {
      const sig = asset.signal ?? ''
      if (!sig || sig === 'FLAT') continue
      const dir = sig === 'BUY' ? 'LONG' : 'SHORT'
      const conf = asset.confidence
      const price = asset.price
      items.push({
        id: `signal-${name}`,
        label: `${name}  ${dir}`,
        description: conf != null ? `${conf}% confidence  ${price?.toFixed?.(5) ?? '—'}` : `${sig}  ${price?.toFixed?.(5) ?? '—'}`,
        icon: <Zap className="w-3.5 h-3.5" strokeWidth={1.5} />,
        action: () => { onSelectAsset?.(name); recordUsage(`signal-${name}`) },
        keywords: [name.toLowerCase(), sig.toLowerCase(), dir.toLowerCase(), 'signal', 'active'],
        section: 'signals',
      })
    }

    return items
  }, [navigate, assetNames, onSelectAsset, assets, exportJson])

  // Filter + group by section
  const grouped = useMemo(() => {
    const q = query.toLowerCase()
    const all = !query
      ? commands
      : commands.filter(c => c.label.toLowerCase().includes(q) || c.keywords.some(k => k.includes(q)))

    // Group by section, preserving section order
    const groups: { section: SectionDef; items: CommandItem[]; startIndex: number }[] = []
    let index = 0
    for (const sectionId of SECTION_ORDER) {
      const sectionItems = all.filter(c => c.section === sectionId)
      if (sectionItems.length > 0) {
        groups.push({ section: SECTIONS[sectionId], items: sectionItems, startIndex: index })
        index += sectionItems.length
      }
    }
    return { all, groups }
  }, [commands, query])

  // Reset selection when results change
  useEffect(() => {
    setSelectedIndex(0)
  }, [query])

  // Scroll selected item into view
  useEffect(() => {
    if (!listRef.current) return
    const selected = listRef.current.querySelector('[data-selected="true"]')
    selected?.scrollIntoView({ block: 'nearest' })
  }, [selectedIndex])

  // Keyboard navigation with vim-style j/k
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const total = grouped.all.length
      if (total === 0) return

      switch (e.key) {
        case 'ArrowDown':
        case 'j':
          e.preventDefault()
          setSelectedIndex(i => Math.min(i + 1, total - 1))
          break
        case 'ArrowUp':
        case 'k':
          e.preventDefault()
          setSelectedIndex(i => Math.max(i - 1, 0))
          break
        case 'Enter': {
          e.preventDefault()
          const item = grouped.all[selectedIndex]
          if (item) {
            recordUsage(item.id)
            item.action()
            setOpen(false)
          }
          break
        }
        case 'Home':
          e.preventDefault()
          setSelectedIndex(0)
          break
        case 'End':
          e.preventDefault()
          setSelectedIndex(total - 1)
          break
      }
    },
    [grouped.all, selectedIndex],
  )

  if (!open) return null

  // Compute flattened indices for the grouped view
  // Each item's global index is its position in grouped.all

  return (
    <div
      className="fixed inset-0 z-modal flex items-start justify-center pt-[10vh] bg-black/40"
      onClick={() => setOpen(false)}
    >
      <div
        className="bg-surface border border-default rounded-xl shadow-modal max-w-lg w-full mx-4 overflow-hidden animate-fade-in"
        onClick={e => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-2 px-3 py-2.5 border-b border-default">
          <Search className="w-4 h-4 text-tertiary shrink-0" strokeWidth={1.5} />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search pages, assets, or run commands…"
            className="flex-1 bg-transparent text-sm text-primary placeholder:text-muted outline-none"
            role="combobox"
            aria-expanded="true"
            aria-controls="cmd-palette-list"
            aria-activedescendant={grouped.all[selectedIndex]?.id}
          />
          <kbd className="text-[10px] font-mono text-tertiary bg-panel px-1.5 py-0.5 rounded border border-default">
            Esc
          </kbd>
        </div>

        {/* Results with section grouping */}
        <div
          id="cmd-palette-list"
          ref={listRef}
          className="max-h-[360px] overflow-y-auto p-1"
          role="listbox"
        >
          {grouped.all.length === 0 ? (
            <div className="px-3 py-6 text-center text-xs text-tertiary">
              No results for &ldquo;{query}&rdquo;
            </div>
          ) : (
            grouped.groups.map(group => (
              <div key={group.section.id}>
                {/* Section header */}
                <div className="flex items-center gap-1.5 px-3 py-1.5 text-2xs font-medium text-tertiary uppercase tracking-wider">
                  {group.section.icon}
                  {group.section.label}
                </div>
                {/* Section items */}
                {group.items.map((item, localIndex) => {
                  const globalIndex = group.startIndex + localIndex
                  const isSelected = globalIndex === selectedIndex
                  return (
                    <button
                      key={item.id}
                      id={item.id}
                      role="option"
                      aria-selected={isSelected}
                      data-selected={isSelected ? 'true' : undefined}
                      onClick={() => { recordUsage(item.id); item.action(); setOpen(false) }}
                      onMouseEnter={() => setSelectedIndex(globalIndex)}
                      className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors ${
                        isSelected
                          ? 'bg-accent-emerald/10 text-primary'
                          : 'text-secondary hover:bg-panel'
                      }`}
                    >
                      <span className={`shrink-0 ${isSelected ? 'text-accent-emerald' : 'text-tertiary'}`}>
                        {item.icon}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-medium truncate">{item.label}</div>
                        <div className="text-[10px] text-tertiary truncate">{item.description}</div>
                      </div>
                      {recentIds.includes(item.id) && (
                        <Clock className="w-2.5 h-2.5 text-tertiary/40 shrink-0" strokeWidth={2} />
                      )}
                    </button>
                  )
                })}
              </div>
            ))
          )}
        </div>

        {/* Footer hint */}
        <div className="flex items-center gap-3 px-3 py-1.5 border-t border-default text-[10px] text-tertiary">
          <span><kbd className="text-[9px] font-mono bg-panel px-1 rounded border border-default">↑↓</kbd> <kbd className="text-[9px] font-mono bg-panel px-1 rounded border border-default">j</kbd><kbd className="text-[9px] font-mono bg-panel px-1 rounded border border-default">k</kbd> Nav</span>
          <span><kbd className="text-[9px] font-mono bg-panel px-1 rounded border border-default">↵</kbd> Select</span>
          <span><kbd className="text-[9px] font-mono bg-panel px-1 rounded border border-default">Esc</kbd> Close</span>
          {recentIds.length > 0 && (
            <span className="flex items-center gap-1 ml-auto">
              <Clock className="w-2.5 h-2.5" strokeWidth={1.5} />
              Recent tracked
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
