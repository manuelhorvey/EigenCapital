import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useSavedLayouts } from '../useSavedLayouts'

const MOCK_STATE = {
  'system-status': true,
  'system-health': true,
  'equity-curve': true,
  'quick-stats': false,
  'open-positions': true,
  'positions-list': false,
  'risk-signals': true,
  'optimizer': false,
}

describe('useSavedLayouts', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('starts with empty presets', () => {
    const { result } = renderHook(() => useSavedLayouts())
    expect(result.current.presets).toEqual([])
    expect(result.current.byPage.size).toBe(0)
  })

  it('saves a layout preset', () => {
    const { result } = renderHook(() => useSavedLayouts())
    
    act(() => {
      result.current.saveLayout('My Layout', 'dashboard', MOCK_STATE)
    })

    expect(result.current.presets).toHaveLength(1)
    expect(result.current.presets[0].name).toBe('My Layout')
    expect(result.current.presets[0].page).toBe('dashboard')
    expect(result.current.presets[0].state).toEqual(MOCK_STATE)
    expect(result.current.presets[0].id).toBeTruthy()
    expect(result.current.presets[0].createdAt).toBeGreaterThan(0)
  })

  it('loads a saved layout by ID', () => {
    const { result } = renderHook(() => useSavedLayouts())
    
    let savedId = ''
    act(() => {
      const preset = result.current.saveLayout('Test', 'dashboard', MOCK_STATE)
      savedId = preset.id
    })

    const loaded = result.current.loadLayout(savedId)
    expect(loaded).toBeTruthy()
    expect(loaded?.name).toBe('Test')
    expect(loaded?.state).toEqual(MOCK_STATE)
  })

  it('returns undefined for unknown ID', () => {
    const { result } = renderHook(() => useSavedLayouts())
    expect(result.current.loadLayout('non-existent')).toBeUndefined()
  })

  it('deletes a layout', () => {
    const { result } = renderHook(() => useSavedLayouts())
    
    let savedId = ''
    act(() => {
      const preset = result.current.saveLayout('To Delete', 'dashboard', MOCK_STATE)
      savedId = preset.id
    })
    expect(result.current.presets).toHaveLength(1)

    act(() => {
      result.current.deleteLayout(savedId)
    })
    expect(result.current.presets).toHaveLength(0)
  })

  it('renames a layout', () => {
    const { result } = renderHook(() => useSavedLayouts())
    
    let savedId = ''
    act(() => {
      const preset = result.current.saveLayout('Old Name', 'dashboard', MOCK_STATE)
      savedId = preset.id
    })

    act(() => {
      result.current.renameLayout(savedId, 'New Name')
    })

    expect(result.current.presets[0].name).toBe('New Name')
  })

  it('updates existing preset when same name and page', () => {
    const { result } = renderHook(() => useSavedLayouts())
    
    act(() => {
      result.current.saveLayout('Duplicate', 'dashboard', MOCK_STATE)
    })
    const firstId = result.current.presets[0].id
    expect(result.current.presets).toHaveLength(1)

    act(() => {
      result.current.saveLayout('Duplicate', 'dashboard', { ...MOCK_STATE, 'quick-stats': true })
    })
    // Should be the same preset, updated
    expect(result.current.presets).toHaveLength(1)
    expect(result.current.presets[0].id).toBe(firstId)
    expect(result.current.presets[0].state['quick-stats']).toBe(true)
  })

  it('filters presets by page', () => {
    const { result } = renderHook(() => useSavedLayouts())
    
    act(() => {
      result.current.saveLayout('Dashboard Layout', 'dashboard', MOCK_STATE)
      result.current.saveLayout('Trading Layout', 'trading', MOCK_STATE)
      result.current.saveLayout('Risk Layout', 'risk', MOCK_STATE)
    })

    const dashboardPresets = result.current.getPresetsForPage('dashboard')
    const tradingPresets = result.current.getPresetsForPage('trading')
    
    expect(dashboardPresets).toHaveLength(1)
    expect(tradingPresets).toHaveLength(1)
    expect(result.current.presets).toHaveLength(3)
  })

  it('persists to localStorage', () => {
    const { result } = renderHook(() => useSavedLayouts())
    
    act(() => {
      result.current.saveLayout('Persistent', 'dashboard', MOCK_STATE)
    })

    const raw = localStorage.getItem('ec_saved_layouts_v1')
    expect(raw).toBeTruthy()
    const parsed = JSON.parse(raw!)
    expect(parsed.presets).toHaveLength(1)
    expect(parsed.presets[0].name).toBe('Persistent')
  })

  it('restores presets from localStorage on mount', () => {
    // Seed localStorage
    const preset = {
      id: 'pre-existing',
      name: 'Pre-existing',
      page: 'dashboard' as const,
      state: MOCK_STATE,
      createdAt: Date.now(),
      updatedAt: Date.now(),
    }
    localStorage.setItem('ec_saved_layouts_v1', JSON.stringify({ presets: [preset] }))

    const { result } = renderHook(() => useSavedLayouts())
    expect(result.current.presets).toHaveLength(1)
    expect(result.current.presets[0].name).toBe('Pre-existing')
  })

  it('builds byPage map correctly', () => {
    const { result } = renderHook(() => useSavedLayouts())
    
    act(() => {
      result.current.saveLayout('Dash', 'dashboard', MOCK_STATE)
      result.current.saveLayout('Trade', 'trading', MOCK_STATE)
      result.current.saveLayout('Dash 2', 'dashboard', MOCK_STATE)
    })

    expect(result.current.byPage.get('dashboard')).toHaveLength(2)
    expect(result.current.byPage.get('trading')).toHaveLength(1)
    expect(result.current.byPage.get('risk')).toBeUndefined()
  })
})
