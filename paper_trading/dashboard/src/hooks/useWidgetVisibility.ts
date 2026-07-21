import { useState, useCallback, useEffect, useMemo } from 'react'

// Per-page widget storage — keyed by page name
// Each page gets its own visibility state, persisted independently.
// This allows users to show widgets on the Dashboard page but hide
// them on other pages without interference.

const STORAGE_PREFIX = 'ec_widget_v2_'

export type WidgetId =
  | 'system-status'
  | 'system-health'
  | 'quick-stats'
  | 'equity-curve'
  | 'open-positions'
  | 'positions-list'
  | 'risk-signals'
  | 'optimizer'

export type PageId = 'dashboard' | 'trading' | 'analytics' | 'risk' | 'reports' | 'settings'

const DEFAULTS: Record<WidgetId, boolean> = {
  'system-status': true,
  'system-health': true,
  'quick-stats': true,
  'equity-curve': true,
  'open-positions': true,
  'positions-list': true,
  'risk-signals': true,
  'optimizer': true,
}

/** Per-page default overrides — some widgets only make sense on certain pages */
const PAGE_DEFAULTS: Partial<Record<PageId, Partial<Record<WidgetId, boolean>>>> = {
  dashboard: {},
  trading: {
    'system-status': false,
    'system-health': false,
    'quick-stats': false,
    'equity-curve': false,
    'open-positions': false,
    'risk-signals': false,
    'optimizer': false,
  },
  analytics: {
    'system-status': false,
    'system-health': false,
    'quick-stats': false,
    'open-positions': false,
    'positions-list': false,
    'risk-signals': false,
    'optimizer': false,
  },
  risk: {
    'system-status': false,
    'system-health': false,
    'quick-stats': false,
    'equity-curve': false,
    'open-positions': false,
    'positions-list': false,
  },
}

const WIDGET_LABELS: Record<WidgetId, string> = {
  'system-status': 'System Status Bar',
  'system-health': 'System Health Summary',
  'quick-stats': 'Quick Stats',
  'equity-curve': 'Equity Curve',
  'open-positions': 'Open Positions',
  'positions-list': 'Positions List',
  'risk-signals': 'Risk Signals',
  'optimizer': 'Optimizer',
}

export function getWidgetLabel(id: WidgetId): string {
  return WIDGET_LABELS[id]
}

function storageKey(page: PageId): string {
  return `${STORAGE_PREFIX}${page}`
}

function load(page: PageId): Record<WidgetId, boolean> {
  const pageDefaults = { ...DEFAULTS, ...PAGE_DEFAULTS[page] }
  try {
    const raw = localStorage.getItem(storageKey(page))
    if (!raw) return pageDefaults
    const parsed = JSON.parse(raw) as Partial<Record<WidgetId, boolean>>
    return { ...pageDefaults, ...parsed }
  } catch {
    return pageDefaults
  }
}

function save(page: PageId, state: Record<WidgetId, boolean>) {
  try {
    localStorage.setItem(storageKey(page), JSON.stringify(state))
  } catch { /* ignore */ }
}

/**
 * Per-page widget visibility hook.
 * Each page gets its own widget layout state, persisted independently in localStorage.
 * @param page - The page context (default: 'dashboard')
 */
export function useWidgetVisibility(page: PageId = 'dashboard') {
  const [visible, setVisible] = useState<Record<WidgetId, boolean>>(() => load(page))

  // Sync to localStorage on change
  useEffect(() => {
    save(page, visible)
  }, [page, visible])

  const isVisible = useCallback((id: WidgetId) => visible[id] ?? true, [visible])

  const toggle = useCallback((id: WidgetId) => {
    setVisible(prev => ({ ...prev, [id]: !prev[id] }))
  }, [])

  const reset = useCallback(() => {
    setVisible({ ...DEFAULTS, ...PAGE_DEFAULTS[page] })
  }, [page])

  const visibleCount = useMemo(() => Object.values(visible).filter(Boolean).length, [visible])
  const totalCount = useMemo(() => Object.keys(visible).length, [visible])

  return { visible, isVisible, toggle, reset, visibleCount, totalCount }
}
