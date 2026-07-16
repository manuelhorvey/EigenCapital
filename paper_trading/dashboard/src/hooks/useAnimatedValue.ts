import { useState, useRef, useEffect } from 'react'

interface UseAnimatedValueOptions {
  /** Duration of the animation in ms. Default 400. */
  duration?: number
  /** Number of decimal places to round to. Default 0. */
  decimals?: number
  /** Easing function. Default is ease-out cubic bezier. */
  easing?: (t: number) => number
}

const defaultEasing = (t: number): number => {
  // Cubic ease-out: 1 - (1 - t)^3
  return 1 - Math.pow(1 - t, 3)
}

/**
 * Smoothly animates between numeric values using requestAnimationFrame.
 * Returns a formatted string and the raw animated number.
 *
 * Usage:
 *   const { value, raw } = useAnimatedValue(portfolioValue, { decimals: 0 })
 *   return <span>{value}</span>
 */
export function useAnimatedValue(
  target: number,
  options: UseAnimatedValueOptions = {},
): { value: string; raw: number } {
  const { duration = 400, decimals = 0, easing = defaultEasing } = options

  const [display, setDisplay] = useState(target)
  const previousRef = useRef(target)
  const rafRef = useRef<number | null>(null)
  const startTimeRef = useRef<number | null>(null)
  const lastAnimatedValueRef = useRef(target)

  useEffect(() => {
    const from = previousRef.current
    if (from === target) {
      setDisplay(target)
      return
    }

    // Honour reduced motion — jump straight to target
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReduced) {
      setDisplay(target)
      previousRef.current = target
      return
    }

    // Use performance.now() for background-tab resilience: if the tab was
    // hidden (and rAF was paused), the elapsed delta will far exceed
    // duration, so we jump to the target instead of animating a stale path.
    const startWall = performance.now()
    startTimeRef.current = null

    const animate = (timestamp: number) => {
      if (startTimeRef.current === null) {
        startTimeRef.current = timestamp
      }

      const elapsedWall = performance.now() - startWall
      // If wall-clock elapsed far exceeds duration, the tab was backgrounded
      // during animation — jump straight to target.
      if (elapsedWall > duration * 2) {
        setDisplay(target)
        previousRef.current = target
        return
      }

      const elapsed = timestamp - startTimeRef.current
      const progress = Math.min(elapsed / duration, 1)
      const easedProgress = easing(progress)

      const current = from + (target - from) * easedProgress
      lastAnimatedValueRef.current = current
      setDisplay(current)

      if (progress < 1) {
        rafRef.current = requestAnimationFrame(animate)
      } else {
        setDisplay(target)
        previousRef.current = target
      }
    }

    rafRef.current = requestAnimationFrame(animate)

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
      }
      // If the effect is cleaned up during animation, record where we left off
      previousRef.current = lastAnimatedValueRef.current
    }
  }, [target, duration, easing])

  const formatted = display.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })

  return { value: formatted, raw: display }
}

export default useAnimatedValue
