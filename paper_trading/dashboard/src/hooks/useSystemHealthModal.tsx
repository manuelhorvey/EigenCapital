import { createContext, useContext, useState, type ReactNode } from 'react'

interface SystemHealthModalState {
  isOpen: boolean
  open: () => void
  close: () => void
}

const SystemHealthModalContext = createContext<SystemHealthModalState | null>(null)

export function SystemHealthModalProvider({ children }: { children: ReactNode }) {
  const [isOpen, setOpen] = useState(false)
  return (
    <SystemHealthModalContext.Provider value={{ isOpen, open: () => setOpen(true), close: () => setOpen(false) }}>
      {children}
    </SystemHealthModalContext.Provider>
  )
}

export function useSystemHealthModal(): SystemHealthModalState {
  const ctx = useContext(SystemHealthModalContext)
  if (!ctx) throw new Error('useSystemHealthModal must be used within SystemHealthModalProvider')
  return ctx
}
