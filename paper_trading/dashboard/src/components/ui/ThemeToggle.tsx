import { useEffect, useState } from 'react'
import { Moon, Sun } from 'lucide-react'

const STORAGE_KEY = 'qf-theme'
const DARK_CLASS = 'dark'

function getStoredTheme(): 'light' | 'dark' | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'light' || v === 'dark') return v
  } catch {}
  return null
}

function getPreferredTheme(): 'light' | 'dark' {
  if (window.matchMedia('(prefers-color-scheme: dark)').matches) return 'dark'
  return 'light'
}

function applyTheme(theme: 'light' | 'dark') {
  document.documentElement.classList.toggle(DARK_CLASS, theme === 'dark')
}

export default function ThemeToggle() {
  const [dark, setDark] = useState(() => {
    const stored = getStoredTheme()
    const theme = stored ?? getPreferredTheme()
    return theme === 'dark'
  })

  useEffect(() => {
    applyTheme(dark ? 'dark' : 'light')
  }, [dark])

  const toggle = () => {
    setDark(prev => {
      const next = !prev
      const theme = next ? 'dark' : 'light'
      try { localStorage.setItem(STORAGE_KEY, theme) } catch {}
      return next
    })
  }

  return (
    <button
      type="button"
      onClick={toggle}
      role="switch"
      aria-checked={dark}
      className="h-8 w-8 flex items-center justify-center rounded-lg border border-default bg-surface hover:border-strong hover:bg-panel-hover transition-colors active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-emerald/50 shadow-panel"
      title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
      aria-label="Theme mode"
    >
      {dark ? (
        <Moon className="w-3.5 h-3.5 text-secondary" strokeWidth={2} />
      ) : (
        <Sun className="w-3.5 h-3.5 text-secondary" strokeWidth={2} />
      )}
    </button>
  )
}
