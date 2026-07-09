import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useAnimatedValue } from '../useAnimatedValue'

describe('useAnimatedValue', () => {
  beforeEach(() => {
    vi.useFakeTimers()

    // Mock requestAnimationFrame — fires synchronously on the next tick
    // using a ref counter so we can advance time precisely.
    let rafId = 0
    const rafCallbacks = new Map<number, FrameRequestCallback>()
    vi.stubGlobal('requestAnimationFrame', vi.fn((cb: FrameRequestCallback) => {
      const id = ++rafId
      rafCallbacks.set(id, cb)
      const timerId = window.setTimeout(() => {
        cb(performance.now())
        rafCallbacks.delete(id)
      }, 16)
      return id
    }))
    vi.stubGlobal('cancelAnimationFrame', vi.fn((id: number) => {
      rafCallbacks.delete(id)
      window.clearTimeout(id)
    }))

    // Mock performance.now to advance with fake timers
    vi.stubGlobal('performance', {
      now: () => Date.now(),
    })

    // Default: no reduced motion preference
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('returns formatted value that eventually reaches target', () => {
    const { result } = renderHook(() => useAnimatedValue(100, { duration: 200, decimals: 0 }))

    // Starts at target value (initial mount uses target as starting point)
    expect(result.current.raw).toBe(100)
    expect(result.current.value).toBe('100')
  })

  it('updates from initial 0 to target when value changes', () => {
    const { result, rerender } = renderHook(
      ({ val }) => useAnimatedValue(val, { duration: 300, decimals: 0 }),
      { initialProps: { val: 0 } },
    )

    expect(result.current.raw).toBe(0)

    // Change target value
    rerender({ val: 100 })

    // Advance past duration + extra RAF frame to ensure animation completes
    act(() => { vi.advanceTimersByTime(350) })
    expect(result.current.raw).toBe(100)
    expect(result.current.value).toBe('100')
  })

  it('handles decimal formatting', () => {
    const { result, rerender } = renderHook(
      ({ val }) => useAnimatedValue(val, { duration: 100, decimals: 2 }),
      { initialProps: { val: 0 } },
    )

    rerender({ val: 3.14159 })
    act(() => { vi.advanceTimersByTime(150) })
    expect(result.current.value).toBe('3.14')
  })

  it('returns target immediately when reduced motion is preferred', () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({
      matches: true, // Reduced motion ON
      media: '',
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })))

    const { result, rerender } = renderHook(
      ({ val }) => useAnimatedValue(val, { duration: 500, decimals: 0 }),
      { initialProps: { val: 0 } },
    )

    rerender({ val: 999 })
    expect(result.current.raw).toBe(999)
    expect(result.current.value).toBe('999')
  })

  it('animates when target is 0', () => {
    const { result, rerender } = renderHook(
      ({ val }) => useAnimatedValue(val, { duration: 100, decimals: 0 }),
      { initialProps: { val: 100 } },
    )

    rerender({ val: 0 })
    act(() => { vi.advanceTimersByTime(150) })
    expect(result.current.raw).toBe(0)
    expect(result.current.value).toBe('0')
  })

  it('animates from high to low', () => {
    const { result, rerender } = renderHook(
      ({ val }) => useAnimatedValue(val, { duration: 200, decimals: 0 }),
      { initialProps: { val: 500 } },
    )

    rerender({ val: 100 })
    act(() => { vi.advanceTimersByTime(250) })
    expect(result.current.raw).toBe(100)
  })

  it('cleans up RAF on unmount', () => {
    const { unmount, rerender } = renderHook(
      ({ val }) => useAnimatedValue(val, { duration: 500, decimals: 0 }),
      { initialProps: { val: 0 } },
    )

    // Start animation
    rerender({ val: 1000 })

    // Unmount before animation completes
    unmount()

    // Should not throw — RAF was cancelled
    act(() => { vi.advanceTimersByTime(500) })
  })

  it('re-animates from a previous settled value to a new target', () => {
    const { result, rerender } = renderHook(
      ({ val }) => useAnimatedValue(val, { duration: 200, decimals: 0 }),
      { initialProps: { val: 0 } },
    )

    // First animation: 0 → 100
    rerender({ val: 100 })
    act(() => { vi.advanceTimersByTime(250) })
    expect(result.current.raw).toBe(100)

    // Second animation: 100 → 50
    rerender({ val: 50 })
    act(() => { vi.advanceTimersByTime(250) })
    expect(result.current.raw).toBe(50)
  })
})
