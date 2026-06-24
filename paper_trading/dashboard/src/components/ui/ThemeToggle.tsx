import { useEffect, useState } from 'react'
import { Moon, Sun } from 'lucide-react'

const STORAGE_KEY = 'qf-theme'
const LIGHT_CLASS = 'light'

function getStoredTheme(): 'light' | 'dark' | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'light' || v === 'dark') return v
  } catch {}
  return null
}

function getPreferredTheme(): 'light' | 'dark' {
  if (window.matchMedia('(prefers-color-scheme: light)').matches) return 'light'
  return 'dark'
}

function applyTheme(theme: 'light' | 'dark') {
  document.documentElement.classList.toggle(LIGHT_CLASS, theme === 'light')
}

export default function ThemeToggle() {
  const [light, setLight] = useState(() => {
    const stored = getStoredTheme()
    const theme = stored ?? getPreferredTheme()
    return theme === 'light'
  })

  useEffect(() => {
    applyTheme(light ? 'light' : 'dark')
  }, [light])

  const toggle = () => {
    setLight(prev => {
      const next = !prev
      const theme = next ? 'light' : 'dark'
      try { localStorage.setItem(STORAGE_KEY, theme) } catch {}
      return next
    })
  }

  return (
    <button
      type="button"
      onClick={toggle}
      className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-md border border-default hover:border-strong hover:bg-panel transition-colors active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-emerald/50"
      title={light ? 'Switch to dark mode' : 'Switch to light mode'}
      aria-label="Toggle theme"
    >
      {light ? (
        <Sun className="w-3 h-3 text-secondary" strokeWidth={2} />
      ) : (
        <Moon className="w-3 h-3 text-secondary" strokeWidth={2} />
      )}
    </button>
  )
}
