import { useRef, useEffect, useCallback } from 'react'

export function useLerpMouse() {
  const pos = useRef({ x: 0, y: 0 })
  const target = useRef({ x: 0, y: 0 })
  const rafId = useRef(0)
  const elementRef = useRef<HTMLDivElement>(null)

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    const el = elementRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    target.current.x = e.clientX - rect.left
    target.current.y = e.clientY - rect.top
  }, [])

  const onMouseLeave = useCallback(() => {
    const el = elementRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    target.current.x = rect.width / 2
    target.current.y = rect.height / 2
  }, [])

  useEffect(() => {
    const el = elementRef.current
    if (!el) return

    function tick() {
      const currentEl = elementRef.current
      if (!currentEl) return
      pos.current.x += (target.current.x - pos.current.x) * 0.08
      pos.current.y += (target.current.y - pos.current.y) * 0.08
      currentEl.style.setProperty('--mx', `${pos.current.x}px`)
      currentEl.style.setProperty('--my', `${pos.current.y}px`)
      rafId.current = requestAnimationFrame(tick)
    }

    rafId.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafId.current)
  }, [])

  return { ref: elementRef, onMouseMove, onMouseLeave }
}
