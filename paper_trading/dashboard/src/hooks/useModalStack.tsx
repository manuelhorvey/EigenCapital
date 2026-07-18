import { createContext, useContext, useState, useCallback, Suspense, type ReactNode, type ComponentType } from 'react'

export interface ModalEntry {
  id: string
  component: ComponentType<any>
  props: Record<string, unknown>
}

interface ModalStackContextValue {
  push: (entry: ModalEntry) => void
  pop: (id?: string) => void
  top: ModalEntry | null
  size: number
}

const ModalStackContext = createContext<ModalStackContextValue>({
  push: () => {},
  pop: () => {},
  top: null,
  size: 0,
})

export function ModalStackProvider({ children }: { children: ReactNode }) {
  const [stack, setStack] = useState<ModalEntry[]>([])

  const push = useCallback((entry: ModalEntry) => {
    setStack(prev => {
      const idx = prev.findIndex(e => e.id === entry.id)
      if (idx >= 0) {
        const next = [...prev]
        next[idx] = entry
        return next
      }
      return [...prev, entry]
    })
  }, [])

  const pop = useCallback((id?: string) => {
    setStack(prev => {
      if (id) return prev.filter(e => e.id !== id)
      return prev.slice(0, -1)
    })
  }, [])

  const top = stack.length > 0 ? stack[stack.length - 1] : null

  return (
    <ModalStackContext.Provider value={{ push, pop, top, size: stack.length }}>
      {children}
      {stack.map((entry, i) => {
        const { component: Component, props: entryProps } = entry
        const isTop = i === stack.length - 1
        return (
          <div key={entry.id} style={{ display: isTop ? undefined : 'none' }}>
            <Suspense fallback={null}>
              <Component {...entryProps} />
            </Suspense>
          </div>
        )
      })}
    </ModalStackContext.Provider>
  )
}

export function useModalStack() {
  return useContext(ModalStackContext)
}
