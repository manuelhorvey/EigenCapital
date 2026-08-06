import { type ReactNode, useRef, useEffect, useState, useCallback } from 'react'

interface EntranceAnimatorProps {
  children: ReactNode
  /** Default is the only active variant: rise + fade into place. */
  variant?: 'fade-up'
  /** Single child animation delay */
  delay?: number
  /** Optional threshold for IntersectionObserver */
  threshold?: number
  /** Root margin for early trigger */
  rootMargin?: string
  className?: string
}

interface UseOnScreenResult {
  ref: (node: HTMLDivElement | null) => void
  visible: boolean
}

function useOnScreen(
  threshold = 0.05,
  rootMargin = '0px 0px -40px 0px'
): UseOnScreenResult {
  const elRef = useRef<HTMLDivElement | null>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const el = elRef.current
    if (!el) return

    // Check reduced motion preference
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReducedMotion) {
      setVisible(true)
      return
    }

    // Fallback: if IntersectionObserver is unavailable, never hide content.
    if (typeof IntersectionObserver === 'undefined') {
      setVisible(true)
      return
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setVisible(true)
          observer.unobserve(el)
        }
      },
      { threshold, rootMargin }
    )

    observer.observe(el)
    return () => observer.disconnect()
  }, [threshold, rootMargin])

  const ref = useCallback((node: HTMLDivElement | null) => {
    elRef.current = node
  }, [])

  return { ref, visible }
}

const HIDDEN = 'opacity-0 translate-y-3'
const VISIBLE = 'opacity-100 translate-y-0'

export default function EntranceAnimator({
  children,
  delay = 0,
  threshold = 0.05,
  rootMargin = '0px 0px -40px 0px',
  className = '',
}: EntranceAnimatorProps) {
  const { ref, visible } = useOnScreen(threshold, rootMargin)

  return (
    <div
      ref={ref}
      className={`transition-all duration-500 ease-out will-change-transform ${
        visible ? VISIBLE : HIDDEN
      } ${className}`}
      style={{
        transitionDelay: `${delay}ms`,
        transitionTimingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)',
      }}
    >
      {children}
    </div>
  )
}