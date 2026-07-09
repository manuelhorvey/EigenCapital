import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  useCallback,
  type ReactNode,
} from 'react'

export type ThemeMode = 'dark' | 'light' | 'system'

interface ThemeContextValue {
  /** The resolved effective theme ('dark' or 'light') — never 'system'. */
  resolved: 'dark' | 'light'
  /** The user's preference ('dark', 'light', or 'system' to follow OS). */
  mode: ThemeMode
  /** Set the user's theme preference. */
  setMode: (mode: ThemeMode) => void
  /** Toggle between dark and light (ignores 'system' — toggles the effective). */
  toggle: () => void
}

const STORAGE_KEY = 'ec_theme'

const ThemeContext = createContext<ThemeContextValue | null>(null)

function getStored(): ThemeMode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'dark' || stored === 'light' || stored === 'system') return stored
  } catch {}
  return 'system'
}

function store(mode: ThemeMode) {
  try { localStorage.setItem(STORAGE_KEY, mode) } catch {}
}

function systemPref(): 'dark' | 'light' {
  if (typeof window === 'undefined') return 'dark'
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

function resolveTheme(mode: ThemeMode): 'dark' | 'light' {
  if (mode === 'system') return systemPref()
  return mode
}

function applyClass(theme: 'dark' | 'light') {
  const root = document.documentElement
  if (theme === 'light') {
    root.classList.add('light')
  } else {
    root.classList.remove('light')
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(getStored)
  const [resolved, setResolved] = useState<'dark' | 'light'>(() => resolveTheme(mode))

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next)
    store(next)
  }, [])

  const toggle = useCallback(() => {
    setModeState(prev => {
      const effective = resolveTheme(prev)
      const next = effective === 'dark' ? 'light' : 'dark'
      store(next)
      return next
    })
  }, [])

  // Apply class when resolved theme changes
  useEffect(() => {
    const r = resolveTheme(mode)
    setResolved(r)
    applyClass(r)
  }, [mode])

  // Listen for system preference changes when mode is 'system'
  useEffect(() => {
    if (mode !== 'system') return

    const mq = window.matchMedia('(prefers-color-scheme: light)')
    const handler = () => {
      const r = systemPref()
      setResolved(r)
      applyClass(r)
    }
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [mode])

  const value = useMemo(
    () => ({ resolved, mode, setMode, toggle }),
    [resolved, mode, setMode, toggle],
  )

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within a ThemeProvider')
  return ctx
}
