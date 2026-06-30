import { useMemo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import Panel from './ui/Panel'
import EmptyState from './ui/EmptyState'

export default function RejectedSignalExplorer() {
  const { data: portfolio } = useSystemSnapshot(systemSelectors.portfolio)
  const adm = portfolio?.admission

  const entries = useMemo(() => {
    if (!adm?.rejection_reasons || Object.keys(adm.rejection_reasons).length === 0) return null
    return Object.entries(adm.rejection_reasons)
  }, [adm])

  if (!entries) {
    return (
      <Panel padding="md">
        <EmptyState message="No rejected signals this cycle" compact />
      </Panel>
    )
  }

  return (
    <Panel padding="md">
      <div className="space-y-2">
        <span className="text-2xs text-tertiary font-medium uppercase tracking-wider">Rejected Signals</span>
        <div className="space-y-1 max-h-48 overflow-y-auto">
          {entries.map(([asset, reason]) => (
            <div key={asset} className="flex items-center justify-between py-1 px-2 rounded bg-red-500/5 text-xs">
              <span className="font-medium text-primary font-mono">{asset}</span>
              <span className="text-gov-red/80 font-mono ml-2 truncate max-w-[200px]">{reason}</span>
            </div>
          ))}
        </div>
      </div>
    </Panel>
  )
}
