import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'

interface CommandPaletteState {
  isOpen: boolean
  open: () => void
  close: () => void
  toggle: () => void
}

const CommandPaletteContext = createContext<CommandPaletteState | null>(null)

export function CommandPaletteProvider({ children }: { children: ReactNode }) {
  const [isOpen, setOpen] = useState(false)

  const open = useCallback(() => setOpen(true), [])
  const close = useCallback(() => setOpen(false), [])
  const toggle = useCallback(() => setOpen(prev => !prev), [])

  // Global shortcut: Cmd/Ctrl+K toggles the palette.
  // Guard: ignore when typing in an input/textarea/contenteditable.
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const tag = target?.tagName
      const typing = tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        toggle()
        return
      }
      if (!typing && e.key === '/' && !isOpen) {
        e.preventDefault()
        open()
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [isOpen, open, toggle])

  return (
    <CommandPaletteContext.Provider value={{ isOpen, open, close, toggle }}>
      {children}
    </CommandPaletteContext.Provider>
  )
}

export function useCommandPalette(): CommandPaletteState {
  const ctx = useContext(CommandPaletteContext)
  if (!ctx) throw new Error('useCommandPalette must be used within CommandPaletteProvider')
  return ctx
}
