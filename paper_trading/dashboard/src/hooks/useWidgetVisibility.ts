import { useState, useCallback, useEffect } from 'react'

const STORAGE_KEY = 'ec_widget_visibility'

export type WidgetId =
  | 'system-status'
  | 'system-health'
  | 'quick-stats'
  | 'equity-curve'
  | 'open-positions'
  | 'positions-list'
  | 'risk-signals'
  | 'optimizer'

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

function load(): Record<WidgetId, boolean> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULTS }
    const parsed = JSON.parse(raw) as Partial<Record<WidgetId, boolean>>
    return { ...DEFAULTS, ...parsed }
  } catch {
    return { ...DEFAULTS }
  }
}

function save(state: Record<WidgetId, boolean>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch { /* ignore */ }
}

export function useWidgetVisibility() {
  const [visible, setVisible] = useState<Record<WidgetId, boolean>>(load)

  useEffect(() => {
    save(visible)
  }, [visible])

  const isVisible = useCallback((id: WidgetId) => visible[id] ?? true, [visible])

  const toggle = useCallback((id: WidgetId) => {
    setVisible(prev => ({ ...prev, [id]: !prev[id] }))
  }, [])

  const reset = useCallback(() => {
    setVisible({ ...DEFAULTS })
  }, [])

  return { visible, isVisible, toggle, reset }
}
