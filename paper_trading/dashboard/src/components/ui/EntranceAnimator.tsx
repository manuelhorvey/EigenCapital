import { type ReactNode, useRef, useEffect, useState, useCallback } from 'react'

type AnimationVariant = 'fade-up' | 'fade-in' | 'scale-in' | 'slide-left'

interface EntranceAnimatorProps {
  children: ReactNode
  /** Animation variant */
  variant?: AnimationVariant
  /** Delay per child in ms when using stagger */
  staggerDelay?: number
  /** Apply as a wrapper around children (each child animates independently) */
  stagger?: boolean
  /** Single child animation delay */
  delay?: number
  /** Optional threshold for IntersectionObserver */
  threshold?: number
  /** Root margin for early trigger */
  rootMargin?: string
  className?: string
  /** Tag to render */
  as?: 'div' | 'section' | 'article'
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

const variantStyles: Record<AnimationVariant, string> = {
  'fade-up': 'opacity-0 translate-y-3',
  'fade-in': 'opacity-0',
  'scale-in': 'opacity-0 scale-[0.97]',
  'slide-left': 'opacity-0 -translate-x-3',
}

const variantVisible: Record<AnimationVariant, string> = {
  'fade-up': 'opacity-100 translate-y-0',
  'fade-in': 'opacity-100',
  'scale-in': 'opacity-100 scale-100',
  'slide-left': 'opacity-100 translate-x-0',
}

function EntranceAnimatorItem({
  children,
  variant = 'fade-up',
  delay = 0,
  className = '',
  as: Tag = 'div',
}: {
  children: ReactNode
  variant?: AnimationVariant
  delay?: number
  className?: string
  as?: 'div' | 'section' | 'article'
}) {
  const { ref, visible } = useOnScreen()

  return (
    <Tag
      ref={ref}
      className={`transition-all duration-500 ease-out will-change-transform ${
        visible
          ? variantVisible[variant]
          : variantStyles[variant]
      } ${className}`}
      style={{
        transitionDelay: `${delay}ms`,
        transitionTimingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)',
      }}
    >
      {children}
    </Tag>
  )
}

export default function EntranceAnimator({
  children,
  variant = 'fade-up',
  staggerDelay = 80,
  stagger = false,
  delay = 0,
  threshold = 0.05,
  rootMargin = '0px 0px -40px 0px',
  className = '',
  as: Tag = 'div',
}: EntranceAnimatorProps) {
  const { ref, visible } = useOnScreen(threshold, rootMargin)

  // Non-stagger mode: just wrap once
  if (!stagger) {
    return (
      <Tag
        ref={ref}
        className={`transition-all duration-500 ease-out will-change-transform ${
          visible
            ? 'opacity-100 translate-y-0'
            : 'opacity-0 translate-y-3'
        } ${className}`}
        style={{
          transitionDelay: `${delay}ms`,
          transitionTimingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)',
        }}
      >
        {children}
      </Tag>
    )
  }

  // Stagger mode: each child animates independently with increasing delay
  const items = Array.isArray(children) ? (children as ReactNode[]) : [children]

  return (
    <Tag ref={ref} className={className}>
      {items.map((child, i) => (
        <EntranceAnimatorItem
          key={i}
          variant={variant}
          delay={i * staggerDelay}
        >
          {child}
        </EntranceAnimatorItem>
      ))}
    </Tag>
  )
}

export { EntranceAnimatorItem }
