import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Search, LayoutDashboard, Zap, BarChart3, Shield, Activity,
  RefreshCw, Eye, Download, AlertTriangle, Settings, FileText,
  Ban, CheckCircle, Terminal,
} from 'lucide-react'
import { useDataExport } from '../hooks/useDataExport'

interface CommandItem {
  id: string
  label: string
  description: string
  icon: React.ReactNode
  action: () => void
  keywords: string[]
}

interface AssetSignal {
  signal?: string
  confidence?: number
  price?: number
  position?: { side?: string; entry?: number }
}

interface CommandPaletteProps {
  /** List of asset names to include in search results. */
  assetNames?: string[]
  /** Called when an asset is selected from search — opens detail panel. */
  onSelectAsset?: (name: string) => void
  /** Optional snapshot asset map for signal search. */
  assets?: Record<string, AssetSignal>
}

/** Cmd+K command palette for navigation, asset search, and shortcut discovery. */
export default function CommandPalette({ assetNames = [], onSelectAsset, assets = {} }: CommandPaletteProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()
  const { exportJson } = useDataExport()

  // Toggle on Cmd+K / Ctrl+K
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setOpen(prev => !prev)
      }
      if (e.key === 'Escape' && open) {
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

  const commands = useMemo<CommandItem[]>(() => {
    const items: CommandItem[] = [
      // ── Navigation ────────────────────────────
      {
        id: 'nav-dashboard',
        label: 'Dashboard',
        description: 'Overview, equity, positions',
        icon: <LayoutDashboard className="w-3.5 h-3.5" strokeWidth={1.5} />,
        action: () => navigate('/'),
        keywords: ['dashboard', 'home', 'overview', 'equity'],
      },
      {
        id: 'nav-trading',
        label: 'Trading',
        description: 'Signals, fills, open trades',
        icon: <Zap className="w-3.5 h-3.5" strokeWidth={1.5} />,
        action: () => navigate('/trading'),
        keywords: ['trading', 'signals', 'trades', 'orders'],
      },
      {
        id: 'nav-analytics',
        label: 'Analytics',
        description: 'Performance attribution, execution quality',
        icon: <BarChart3 className="w-3.5 h-3.5" strokeWidth={1.5} />,
        action: () => navigate('/analytics'),
        keywords: ['analytics', 'attribution', 'execution', 'quality', 'slippage'],
      },
      {
        id: 'nav-risk',
        label: 'Governance & Risk',
        description: 'Health scores, governance, constraints',
        icon: <Shield className="w-3.5 h-3.5" strokeWidth={1.5} />,
        action: () => navigate('/risk'),
        keywords: ['risk', 'governance', 'health', 'constraints'],
      },
      {
        id: 'nav-reports',
        label: 'Reports',
        description: 'Download reports, audit log',
        icon: <FileText className="w-3.5 h-3.5" strokeWidth={1.5} />,
        action: () => navigate('/reports'),
        keywords: ['reports', 'audit', 'download', 'export', 'weekly'],
      },
      {
        id: 'nav-settings',
        label: 'Settings',
        description: 'Preferences, theme, API keys',
        icon: <Settings className="w-3.5 h-3.5" strokeWidth={1.5} />,
        action: () => navigate('/settings'),
        keywords: ['settings', 'preferences', 'theme', 'api', 'config'],
      },

      // ── Actions ───────────────────────────────
      {
        id: 'action-refresh',
        label: 'Refresh Dashboard',
        description: 'Force refresh all dashboard data',
        icon: <RefreshCw className="w-3.5 h-3.5" strokeWidth={1.5} />,
        action: () => { window.location.reload() },
        keywords: ['refresh', 'reload', 'update', 'sync'],
      },
      {
        id: 'action-toggle-halts',
        label: 'Toggle Halted Assets',
        description: 'Show or hide halted assets in the list',
        icon: <Eye className="w-3.5 h-3.5" strokeWidth={1.5} />,
        action: () => navigate('/risk'),
        keywords: ['halt', 'toggle', 'show', 'hide', 'halted'],
      },
      {
        id: 'action-export',
        label: 'Export Data',
        description: 'Download portfolio state as JSON',
        icon: <Download className="w-3.5 h-3.5" strokeWidth={1.5} />,
        action: () => exportJson('/state-bundle.json', { filename: `eigencapital-snapshot-${Date.now()}` }),
        keywords: ['export', 'download', 'json', 'backup', 'save'],
      },
      {
        id: 'action-alerts',
        label: 'Critical Alerts',
        description: 'View all active system alerts',
        icon: <AlertTriangle className="w-3.5 h-3.5" strokeWidth={1.5} />,
        action: () => navigate('/risk'),
        keywords: ['alert', 'critical', 'error', 'warning', 'notification'],
      },
      {
        id: 'action-halt-engine',
        label: 'Halt Engine',
        description: 'Emergency halt all trading activity',
        icon: <Ban className="w-3.5 h-3.5" strokeWidth={1.5} />,
        action: () => {
          if (window.confirm('Are you sure you want to halt the engine?')) {
            fetch('/api/engine/halt', { method: 'POST' }).catch(() => {})
          }
        },
        keywords: ['halt', 'emergency', 'stop', 'engine', 'kill', 'panic'],
      },
      {
        id: 'action-acknowledge-weekly',
        label: 'Acknowledge Weekly Review',
        description: 'Acknowledge the current weekly performance review',
        icon: <CheckCircle className="w-3.5 h-3.5" strokeWidth={1.5} />,
        action: () => {
          fetch('/weekly-review/acknowledge', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => {})
        },
        keywords: ['acknowledge', 'weekly', 'review', 'confirm'],
      },
      {
        id: 'action-clear-cache',
        label: 'Clear API Cache',
        description: 'Clear server-side API response cache',
        icon: <Terminal className="w-3.5 h-3.5" strokeWidth={1.5} />,
        action: () => {
          fetch('/api/clear-cache', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => {})
        },
        keywords: ['cache', 'clear', 'refresh', 'api'],
      },
    ]

    // Add asset search items
    for (const name of assetNames) {
      items.push({
        id: `asset-${name}`,
        label: name,
        description: 'Open asset detail panel',
        icon: <Activity className="w-3.5 h-3.5" strokeWidth={1.5} />,
        action: () => onSelectAsset?.(name),
        keywords: [name.toLowerCase(), 'asset', 'position'],
      })
    }

    // Add signal search items from snapshot
    for (const [name, asset] of Object.entries(assets)) {
      const sig = asset.signal ?? ''
      const conf = asset.confidence
      if (!sig || sig === 'FLAT') continue
      const dir = sig === 'BUY' ? 'LONG' : 'SHORT'
      const confStr = conf != null ? `${conf}%` : ''
      items.push({
        id: `signal-${name}`,
        label: `${name} · ${dir}`,
        description: confStr
          ? `Signal: ${sig} · ${confStr} · Price: ${asset.price?.toFixed?.(5) ?? '—'}`
          : `Signal: ${sig} · Price: ${asset.price?.toFixed?.(5) ?? '—'}`,
        icon: <Activity className="w-3.5 h-3.5" strokeWidth={1.5} />,
        action: () => onSelectAsset?.(name),
        keywords: [name.toLowerCase(), sig.toLowerCase(), dir.toLowerCase(), 'signal', 'active'],
      })
    }

    return items
  }, [navigate, assetNames, onSelectAsset, assets, exportJson])

  const filtered = useMemo(() => {
    if (!query) return commands
    const q = query.toLowerCase()
    return commands.filter(
      c =>
        c.label.toLowerCase().includes(q) ||
        c.keywords.some(k => k.includes(q)),
    )
  }, [commands, query])

  // Reset selection when results change
  useEffect(() => {
    setSelectedIndex(0)
  }, [query])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelectedIndex(i => Math.min(i + 1, filtered.length - 1))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelectedIndex(i => Math.max(i - 1, 0))
      } else if (e.key === 'Enter' && filtered[selectedIndex]) {
        e.preventDefault()
        filtered[selectedIndex].action()
        setOpen(false)
      }
    },
    [filtered, selectedIndex],
  )

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[200] flex items-start justify-center pt-[10vh] bg-black/40"
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
          />
          <kbd className="text-[10px] font-mono text-tertiary bg-panel px-1.5 py-0.5 rounded border border-default">
            Esc
          </kbd>
        </div>

        {/* Results */}
        <div className="max-h-64 overflow-y-auto p-1" role="listbox">
          {filtered.length === 0 ? (
            <div className="px-3 py-6 text-center text-xs text-tertiary">
              No results for "{query}"
            </div>
          ) : (
            filtered.map((item, i) => (
              <button
                key={item.id}
                role="option"
                aria-selected={i === selectedIndex}
                onClick={() => { item.action(); setOpen(false) }}
                onMouseEnter={() => setSelectedIndex(i)}
                className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors ${
                  i === selectedIndex
                    ? 'bg-accent-emerald/10 text-primary'
                    : 'text-secondary hover:bg-panel'
                }`}
              >
                <span className={`shrink-0 ${i === selectedIndex ? 'text-accent-emerald' : 'text-tertiary'}`}>
                  {item.icon}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-medium truncate">{item.label}</div>
                  <div className="text-[10px] text-tertiary truncate">{item.description}</div>
                </div>
              </button>
            ))
          )}
        </div>

        {/* Footer hint */}
        <div className="flex items-center gap-3 px-3 py-1.5 border-t border-default text-[10px] text-tertiary">
          <span><kbd className="text-[9px] font-mono bg-panel px-1 rounded border border-default">↑↓</kbd> Navigate</span>
          <span><kbd className="text-[9px] font-mono bg-panel px-1 rounded border border-default">↵</kbd> Select</span>
          <span><kbd className="text-[9px] font-mono bg-panel px-1 rounded border border-default">Esc</kbd> Close</span>
        </div>
      </div>
    </div>
  )
}
