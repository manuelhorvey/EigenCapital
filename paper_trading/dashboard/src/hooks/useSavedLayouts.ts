import { useState, useCallback, useEffect, useMemo } from 'react'
import type { WidgetId, PageId } from './useWidgetVisibility'

// ── Types ──────────────────────────────────────────────────────────

export interface LayoutPreset {
  id: string
  name: string
  description?: string
  page: PageId
  state: Record<WidgetId, boolean>
  createdAt: number
  updatedAt: number
}

interface SavedLayoutsData {
  presets: LayoutPreset[]
}

// ── Constants ──────────────────────────────────────────────────────

const STORAGE_KEY = 'ec_saved_layouts_v1'

// ── Persistence ────────────────────────────────────────────────────

function load(): LayoutPreset[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as SavedLayoutsData
    return Array.isArray(parsed.presets) ? parsed.presets : []
  } catch {
    return []
  }
}

function save(presets: LayoutPreset[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ presets }))
  } catch {
    /* storage full or unavailable */
  }
}

function generateId(): string {
  return `layout-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

// ── Hook ───────────────────────────────────────────────────────────

export function useSavedLayouts() {
  const [presets, setPresets] = useState<LayoutPreset[]>(load)

  // Sync to localStorage on change
  useEffect(() => {
    save(presets)
  }, [presets])

  /** Save the current widget visibility state as a named layout preset. */
  const saveLayout = useCallback(
    (name: string, page: PageId, state: Record<WidgetId, boolean>, description?: string): LayoutPreset => {
      const now = Date.now()
      let preset: LayoutPreset = {
        id: generateId(),
        name,
        description,
        page,
        state: { ...state },
        createdAt: now,
        updatedAt: now,
      }
      setPresets(prev => {
        // If a preset with the same name exists for this page, update it
        const existing = prev.findIndex(p => p.name === name && p.page === page)
        if (existing >= 0) {
          const updated = [...prev]
          // Preserve original ID when updating
          updated[existing] = { ...updated[existing], ...preset, id: updated[existing].id, createdAt: updated[existing].createdAt, updatedAt: now }
          preset = { ...updated[existing] }
          return updated
        }
        return [...prev, preset]
      })
      return preset
    },
    [],
  )

  /** Load a layout preset by ID, returning its widget state. */
  const loadLayout = useCallback(
    (id: string): LayoutPreset | undefined => {
      return presets.find(p => p.id === id)
    },
    [presets],
  )

  /** Delete a layout preset by ID. */
  const deleteLayout = useCallback((id: string) => {
    setPresets(prev => prev.filter(p => p.id !== id))
  }, [])

  /** Rename a layout preset. */
  const renameLayout = useCallback((id: string, name: string) => {
    setPresets(prev =>
      prev.map(p => (p.id === id ? { ...p, name, updatedAt: Date.now() } : p)),
    )
  }, [])

  /** Get presets filtered by page. */
  const getPresetsForPage = useCallback(
    (page: PageId): LayoutPreset[] => {
      return presets.filter(p => p.page === page)
    },
    [presets],
  )

  const byPage = useMemo(() => {
    const map = new Map<PageId, LayoutPreset[]>()
    for (const p of presets) {
      const existing = map.get(p.page) ?? []
      existing.push(p)
      map.set(p.page, existing)
    }
    return map
  }, [presets])

  return {
    presets,
    byPage,
    saveLayout,
    loadLayout,
    deleteLayout,
    renameLayout,
    getPresetsForPage,
  }
}
