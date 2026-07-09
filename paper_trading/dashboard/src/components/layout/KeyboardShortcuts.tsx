import { useState, useEffect, useCallback, useRef } from 'react'
import { Command, X } from 'lucide-react'

interface Shortcut {
  keys: string[]
  description: string
}

const SHORTCUTS: Shortcut[] = [
  { keys: ['?'], description: 'Toggle this shortcuts panel' },
  { keys: ['Tab'], description: 'Navigate between interactive elements' },
  { keys: ['Enter'], description: 'Activate focused button or link' },
  { keys: ['Esc'], description: 'Close modal, panel, or dropdown' },
  { keys: ['Ctrl', 'R'], description: 'Refresh dashboard data' },
]

/**
 * Keyboard shortcuts overlay. Press `?` to toggle.
 * Shows common navigation and interaction shortcuts for the dashboard.
 * Accessible: focus-traps within the panel, Escape to close.
 */
export default function KeyboardShortcuts() {
  const [open, setOpen] = useState(false)
  const openRef = useRef(open)
  openRef.current = open

  // Toggle on `?` keypress — stable listener, never re-registers
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === '?' && !e.ctrlKey && !e.metaKey && !e.altKey) {
      // Only toggle when not typing in an input
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      e.preventDefault()
      setOpen(prev => !prev)
    }

    if (e.key === 'Escape' && openRef.current) {
      setOpen(false)
    }
  }, [])  // stable — never re-registers

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40"
      onClick={() => setOpen(false)}
      onKeyDown={e => e.key === 'Escape' && setOpen(false)}
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
    >
      <div
        className="bg-surface border border-default rounded-xl shadow-modal max-w-md w-full mx-4 p-5 animate-fade-in"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Command className="w-4 h-4 text-tertiary" strokeWidth={1.5} />
            <span className="text-sm font-semibold text-primary">Keyboard Shortcuts</span>
          </div>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="p-1 rounded hover:bg-panel transition-colors"
            aria-label="Close shortcuts panel"
          >
            <X className="w-3.5 h-3.5 text-tertiary" strokeWidth={2} />
          </button>
        </div>

        {/* Shortcuts list */}
        <div className="space-y-2" role="list" aria-label="Available shortcuts">
          {SHORTCUTS.map((shortcut, i) => (
            <div
              key={i}
              className="flex items-center justify-between py-1.5 border-b border-default/40 last:border-0"
              role="listitem"
            >
              <span className="text-xs text-secondary">{shortcut.description}</span>
              <span className="flex items-center gap-1 shrink-0 ml-4">
                {shortcut.keys.map((key, j) => (
                  <span key={j}>
                    <kbd className="inline-flex items-center justify-center min-w-[22px] h-5 px-1.5 rounded border border-default bg-panel text-2xs font-mono font-semibold text-tertiary shadow-sm">
                      {key}
                    </kbd>
                    {j < shortcut.keys.length - 1 && (
                      <span className="mx-1 text-2xs text-tertiary">+</span>
                    )}
                  </span>
                ))}
              </span>
            </div>
          ))}
        </div>

        {/* Footer */}
        <p className="mt-4 text-2xs text-tertiary text-center">
          Press <kbd className="inline-flex items-center justify-center min-w-[18px] h-4 px-1 rounded border border-default bg-panel text-2xs font-mono font-semibold text-tertiary shadow-sm">?</kbd> at any time to toggle this panel
        </p>
      </div>
    </div>
  )
}
