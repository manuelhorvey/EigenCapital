import { useMemo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import AssetCard from './AssetCard'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import EmptyState from './ui/EmptyState'
import { Skeleton } from './ui/Skeleton'

export default function AssetGrid() {
  const { data: assets, isPending } = useSystemSnapshot(systemSelectors.assets)
  const assetNames = useMemo(() => {
    if (!assets) return []
    return Object.keys(assets).sort()
  }, [assets])

  if (isPending) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-28 rounded-lg" />
        ))}
      </div>
    )
  }

  if (assetNames.length === 0) {
    return (
      <Panel className="p-4">
        <SectionHeader title="Assets" accent="neutral" />
        <EmptyState message="No assets available yet" compact />
      </Panel>
    )
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
      {assetNames.map(name => (
        <AssetCard key={name} name={name} />
      ))}
    </div>
  )
}
