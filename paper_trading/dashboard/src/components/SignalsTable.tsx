import { useMemo, useState } from 'react'
import { Search, ListFilter } from 'lucide-react'
import { usePortfolioState } from '../hooks/usePortfolioState'
import { formatAssetPrice } from '../utils/format'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import EmptyState from './ui/EmptyState'
import { TableSkeleton } from './ui/Skeleton'
import { governanceDot } from './ui/governance'

function signalClass(signal?: string): string {
  if (signal === 'BUY') return 'text-gov-green'
  if (signal === 'SELL') return 'text-gov-red'
  return 'text-muted'
}

function confClass(conf: number): string {
  if (conf >= 60) return 'text-gov-green'
  if (conf >= 45) return 'text-gov-yellow'
  return 'text-gov-red'
}

function ddClass(dd: number): string {
  if (dd > -3) return 'text-gov-green'
  if (dd > -5) return 'text-gov-yellow'
  return 'text-gov-red'
}

export default function SignalsTable() {
  const [search, setSearch] = useState('')
  const { data, isPending } = usePortfolioState()
  const rows = useMemo(() => {
    if (!data?.assets) return []
    return Object.entries(data.assets)
      .filter(([name]) => name.toLowerCase().includes(search.toLowerCase()))
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, asset]) => {
        const sig = asset.last_signal
        const m = asset.metrics
        const alloc = data.portfolio?.allocations?.[name] ?? 0
        return { name, sig, m, alloc }
      })
  }, [data, search])

  if (isPending) return <TableSkeleton rows={6} />

  if (rows.length === 0) {
    return (
      <Panel className="p-4">
        <SectionHeader title="Signals" accent="emerald" />
        <EmptyState message="No assets loaded" compact />
      </Panel>
    )
  }

  return (
    <Panel className="overflow-hidden">
      <SectionHeader
        title="Signals"
        accent="emerald"
        meta={
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-muted pointer-events-none" />
              <input
                type="text"
                placeholder="Filter…"
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="input-terminal w-28 sm:w-32 pl-7"
              />
            </div>
            <span className="text-[10px] text-tertiary font-mono tabular-nums">{rows.length}</span>
          </div>
        }
      />
      <div className="overflow-x-auto -mx-1">
        <table className="w-full text-[11px] min-w-[500px]">
          <thead>
            <tr className="border-b border-default">
              <th className="table-header text-left py-2 pr-3">Asset</th>
              <th className="table-header text-left py-2 pr-3">Signal</th>
              <th className="table-header text-right py-2 pr-3">Conf</th>
              <th className="table-header text-right py-2 pr-3">Price</th>
              <th className="table-header text-right py-2 pr-3">Alloc</th>
              <th className="table-header text-right py-2 pr-3">Ret</th>
              <th className="table-header text-right py-2">DD</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ name, sig, m, alloc }, i) => (
              <tr
                key={name}
                className={`border-b border-default/40 table-row-hover ${
                  i % 2 === 1 ? 'bg-panel/30' : ''
                }`}
              >
                <td className="py-2 pr-3">
                  <span className="font-semibold text-primary text-xs font-mono">{name}</span>
                </td>
                <td className="py-2 pr-3">
                  <span className={`signal-pill ${
                    sig?.signal === 'BUY'
                      ? 'signal-pill-buy'
                      : sig?.signal === 'SELL'
                        ? 'signal-pill-sell'
                        : 'signal-pill-flat'
                  }`}>
                    {sig?.signal === 'BUY' ? 'LONG' : sig?.signal === 'SELL' ? 'SHORT' : 'FLAT'}
                  </span>
                </td>
                <td className={`py-2 pr-3 text-right font-mono tabular-nums ${confClass(sig?.confidence ?? 0)}`}>
                  {(sig?.confidence ?? 0).toFixed(0)}
                </td>
                <td className="py-2 pr-3 text-right font-mono text-secondary tabular-nums">
                  {formatAssetPrice(sig?.close_price)}
                </td>
                <td className="py-2 pr-3 text-right font-mono text-tertiary tabular-nums">
                  {(alloc * 100).toFixed(0)}%
                </td>
                <td
                  className={`py-2 pr-3 text-right font-mono tabular-nums ${
                    (m?.mtm_return ?? 0) >= 0 ? 'text-gov-green' : 'text-gov-red'
                  }`}
                >
                  {(m?.mtm_return ?? 0).toFixed(2)}
                </td>
                <td className={`py-2 text-right font-mono tabular-nums ${ddClass(m?.drawdown ?? 0)}`}>
                  {(m?.drawdown ?? 0).toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
