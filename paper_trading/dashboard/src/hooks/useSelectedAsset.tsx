import { createContext, useContext, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

interface SelectedAssetContextValue {
  selectedAsset: string | null
  setSelectedAsset: (name: string | null) => void
  deepDiveAsset: string | null
  setDeepDiveAsset: (name: string | null) => void
  deepDiveOpen: boolean
}

const EMPTY = {
  selectedAsset: null,
  setSelectedAsset: () => {},
  deepDiveAsset: null,
  setDeepDiveAsset: () => {},
  deepDiveOpen: false,
} satisfies SelectedAssetContextValue

export const SelectedAssetContext = createContext<SelectedAssetContextValue>(EMPTY)

export function SelectedAssetProvider({ children }: { children: React.ReactNode }) {
  const [searchParams, setSearchParams] = useSearchParams()

  const selectedAsset = searchParams.get('asset')
  const deepDiveOpen = searchParams.get('deepDive') === 'true'
  const deepDiveAsset = deepDiveOpen ? selectedAsset : null

  const setSelectedAsset = useCallback(
    (name: string | null) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (name) {
            next.set('asset', name)
          } else {
            next.delete('asset')
          }
          next.delete('deepDive')
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const setDeepDiveAsset = useCallback(
    (name: string | null) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (name) {
            next.set('asset', name)
            next.set('deepDive', 'true')
          } else {
            next.delete('deepDive')
          }
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  return (
    <SelectedAssetContext.Provider value={{ selectedAsset, setSelectedAsset, deepDiveAsset, setDeepDiveAsset, deepDiveOpen }}>
      {children}
    </SelectedAssetContext.Provider>
  )
}

export function useSelectedAsset() {
  return useContext(SelectedAssetContext)
}
