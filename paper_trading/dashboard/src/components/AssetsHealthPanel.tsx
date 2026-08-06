import { useMemo } from 'react'
import type { ReactNode } from 'react'
import { Activity, ShieldAlert, ShieldCheck, AlertTriangle } from 'lucide-react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import { Skeleton } from './ui/Skeleton'
import EmptyState from './ui/EmptyState'
import { assetHealth, healthColor, healthText, healthLabel, type AssetHealth } from '../utils/assetHealth'

interface HealthCell {
  key: AssetHealth
  label: string
  count: number
  text: string
  dot: string
  icon: ReactNode
}

export default function AssetsHealthPanel() {
  const { data: assets, isPending } = useSystemSnapshot(systemSelectors.assets)
  const { data: snapshot } = useSystemSnapshot(systemSelectors.snapshot)

  const counts = useMemo(() => {
    const c: Record<AssetHealth, number> = { healthy: 0, warning: 0, critical: 0, idle: 0 }
    let ddSum = 0
    let ddN = 0
    let validitySum = 0
    let validityN = 0
    if (assets) {
      for (const a of Object.values(assets)) {
        const h = assetHealth(a)
        c[h] += 1
        if (typeof a.metrics?.drawdown === 'number') { ddSum += a.metrics.drawdown; ddN += 1 }
        if (typeof a.validity_exposure === 'number') { validitySum += a.validity_exposure; validityN += 1 }
      }
    }
    return { c, avgDd: ddN > 0 ? ddSum / ddN : null, avgVal: validityN > 0 ? (validitySum / validityN) * 100 : null }
  }, [assets])

  const open = snapshot?.portfolio?.open_positions ?? 0
  const maxOpen = snapshot?.portfolio?.pek?.portfolio_snapshot?.max_concurrent ?? null

  const cells: HealthCell[] = [
    { key: 'healthy', label: healthLabel.healthy, count: counts.c.healthy, icon: <ShieldCheck className="w-3.5 h-3.5" strokeWidth={2} />, text: healthText.healthy, dot: healthColor.healthy },
    { key: 'warning', label: healthLabel.warning, count: counts.c.warning, icon: <AlertTriangle className="w-3.5 h-3.5" strokeWidth={2} />, text: healthText.warning, dot: healthColor.warning },
    { key: 'critical', label: healthLabel.critical, count: counts.c.critical, icon: <ShieldAlert className="w-3.5 h-3.5" strokeWidth={2} />, text: healthText.critical, dot: healthColor.critical },
    { key: 'idle', label: healthLabel.idle, count: counts.c.idle, icon: <Activity className="w-3.5 h-3.5" strokeWidth={2} />, text: healthText.idle, dot: healthColor.idle },
  ]

  if (isPending) return <Skeleton className="h-28 rounded-lg" shimmer />

  if (!assets || Object.keys(assets).length === 0) {
    return (
      <Panel className="p-4">
        <SectionHeader title="Assets Health" accent="emerald" />
        <EmptyState message="No asset data yet" compact />
      </Panel>
    )
  }

  return (
    <Panel className="p-3.5 sm:p-4">
      <SectionHeader
        title="Assets Health"
        accent="emerald"
        meta={
          <span className="text-2xs font-mono tabular-nums text-tertiary">
            {open}/{maxOpen ?? '—'} open
          </span>
        }
      />
      <div className="grid grid-cols-2 gap-2">
        {cells.map(cell => (
          <div key={cell.key} className="rounded-lg border border-default bg-panel/50 px-3 py-2.5 flex items-center justify-between gap-2">
            <div className="min-w-0">
              <div className={`flex items-center gap-1.5 ${cell.text}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${cell.dot}`} />
                <span className="text-[9px] font-semibold uppercase tracking-wider">{cell.label}</span>
              </div>
              <div className={`mt-0.5 text-lg font-semibold font-mono tabular-nums ${cell.text}`}>{cell.count}</div>
            </div>
            <span className={cell.text}>{cell.icon}</span>
          </div>
        ))}
      </div>
      <div className="mt-2.5 flex items-center gap-4 px-1 text-2xs font-mono tabular-nums text-tertiary">
        <span>Avg DD {counts.avgDd != null ? `${counts.avgDd >= 0 ? '+' : ''}${counts.avgDd.toFixed(2)}%` : '—'}</span>
        <span>Avg validity {counts.avgVal != null ? `${counts.avgVal.toFixed(0)}%` : '—'}</span>
      </div>
    </Panel>
  )
}