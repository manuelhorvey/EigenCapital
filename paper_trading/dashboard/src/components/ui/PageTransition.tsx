import { useState, useEffect, useRef, type ReactNode } from 'react'

interface PageTransitionProps {
  children: ReactNode
  /** Transition key — typically a route path or page identifier.
   *  When this changes, the page fades out and back in. */
  locationKey: string
  /** Duration of the exit/enter transition in ms. Default 200. */
  durationMs?: number
  className?: string
  /** Callback fired when the transition reaches the 'visible' phase.
   *  Useful for focus management after route changes. */
  onVisible?: () => void
}

type TransitionPhase = 'enter' | 'visible' | 'exit'

/**
 * Page-level transition wrapper. Animates content out and back in
 * when the locationKey changes (e.g., on route navigation).
 * Uses refs for timer tracking to avoid nested-setTimeout leaks.
 *
 * Usage:
 *   <PageTransition locationKey={location.pathname}>
 *     <Routes>…</Routes>
 *   </PageTransition>
 */
export default function PageTransition({
  children,
  locationKey,
  durationMs = 200,
  className = '',
  onVisible,
}: PageTransitionProps) {
  const [phase, setPhase] = useState<TransitionPhase>('enter')
  const prevKeyRef = useRef(locationKey)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onVisibleRef = useRef(onVisible)
  onVisibleRef.current = onVisible

  useEffect(() => {
    // Clear any pending timer from previous transition
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
    }

    if (locationKey !== prevKeyRef.current) {
      prevKeyRef.current = locationKey
      // Exit → enter chain using rAF to ensure browser composites before next state
      setPhase('exit')

      timerRef.current = setTimeout(() => {
        setPhase('enter')
        timerRef.current = setTimeout(() => {
          setPhase('visible')
          timerRef.current = null
          onVisibleRef.current?.()
        }, durationMs)
      }, durationMs)

      return () => {
        if (timerRef.current !== null) {
          clearTimeout(timerRef.current)
        }
      }
    }

    // Initial mount: enter → visible
    if (phase === 'enter') {
      timerRef.current = setTimeout(() => {
        setPhase('visible')
        timerRef.current = null
        onVisibleRef.current?.()
      }, durationMs)

      return () => {
        if (timerRef.current !== null) {
          clearTimeout(timerRef.current)
        }
      }
    }
  }, [locationKey, durationMs])

  // Separate effect to listen for prevKey changes — no longer needed since
  // we derive everything from locationKey in a single effect.

  const opacityClass = phase === 'visible' ? 'opacity-100' : 'opacity-0'

  return (
    <div
      className={`transition-opacity ease-out ${opacityClass} ${className}`}
      style={{ transitionDuration: `${durationMs}ms` }}
      aria-hidden={phase === 'exit'}
    >
      {children}
    </div>
  )
}
