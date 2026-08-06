import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useToast } from '../components/toast/Toast'
import { SHORTCUT_TO_ROUTE, SHORTCUT_SUMMARY } from '../lib/navigation'

export function useGlobalShortcuts() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const gPending = useRef(false)
  const gTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const tag = target?.tagName
      const typing = tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable

      // '?' opens shortcut help (ignore while typing)
      if (!typing && e.key === '?') {
        e.preventDefault()
        toast({
          title: 'Keyboard shortcuts',
          description: `⌘K / Ctrl+K palette · g then ${SHORTCUT_SUMMARY} to navigate · / to search`,
          variant: 'info',
          duration: 6000,
        })
        return
      }

      if (!typing && e.key === 'g') {
        gPending.current = true
        gTimer.current && clearTimeout(gTimer.current)
        gTimer.current = setTimeout(() => {
          gPending.current = false
        }, 900)
        return
      }

      const route = SHORTCUT_TO_ROUTE[e.key]
      if (gPending.current && !typing && route) {
        e.preventDefault()
        navigate(route)
        window.scrollTo({ top: 0 })
        gPending.current = false
        gTimer.current && clearTimeout(gTimer.current)
      }
    }

    window.addEventListener('keydown', handleKey)
    return () => {
      window.removeEventListener('keydown', handleKey)
      gTimer.current && clearTimeout(gTimer.current)
    }
  }, [navigate, toast])

  return null
}
