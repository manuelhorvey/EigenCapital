import { useCallback, useRef } from 'react'

export function useTilt() {
  const ref = useRef<HTMLDivElement>(null)
  const timeoutId = useRef(0)

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    const card = ref.current
    if (!card) return
    const rect = card.getBoundingClientRect()
    const offsetX = e.clientX - rect.left - rect.width / 2
    const offsetY = e.clientY - rect.top - rect.height / 2
    card.style.transform = `perspective(1000px) rotateX(${-offsetY * 0.015}deg) rotateY(${offsetX * 0.015}deg)`
  }, [])

  const onMouseLeave = useCallback(() => {
    const card = ref.current
    if (!card) return
    card.style.transform = 'perspective(1000px) rotateX(0deg) rotateY(0deg)'
    card.style.transition = 'transform 0.4s ease'
    clearTimeout(timeoutId.current)
    timeoutId.current = window.setTimeout(() => {
      if (card) card.style.transition = 'transform 0.1s ease'
    }, 400)
  }, [])

  return { ref, onMouseMove, onMouseLeave }
}
