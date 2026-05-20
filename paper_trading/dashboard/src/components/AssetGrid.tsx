import { useMemo } from 'react'
import { usePortfolioState } from '../hooks/usePortfolioState'
import AssetCard from './AssetCard'

export default function AssetGrid() {
  const { data, isPending } = usePortfolioState()
  const assetNames = useMemo(() => data?.assets ? Object.keys(data.assets).sort() : [], [data])

  if (isPending) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="card-gradient card-border rounded-xl p-4 animate-pulse">
            <div className="h-4 bg-gray-800 rounded w-1/3 mb-3" />
            <div className="h-3 bg-gray-800/50 rounded w-2/3 mb-2" />
            <div className="h-3 bg-gray-800/50 rounded w-1/2" />
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {assetNames.map(name => (
        <AssetCard key={name} name={name} />
      ))}
    </div>
  )
}
