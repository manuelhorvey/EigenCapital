import { useMemo } from 'react'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import { usePSI } from '../hooks/usePSI'
import type { PSIFeatureEntry, PSIAssetStatus } from '../hooks/usePSI'

function psiColor(cls: string): string {
  switch (cls) {
    case 'SEVERE':
      return 'text-gov-red'
    case 'MODERATE':
      return 'text-gov-yellow'
    default:
      return 'text-gov-green'
  }
}

function psiBg(cls: string): string {
  switch (cls) {
    case 'SEVERE':
      return 'bg-gov-red-muted border-gov-red/20'
    case 'MODERATE':
      return 'bg-gov-yellow-muted border-gov-yellow/20'
    default:
      return 'bg-gov-green-muted border-gov-green/20'
  }
}

function trendArrow(trend: string, cls: string): string {
  if (trend === 'INCREASING') return '\u2191'
  if (trend === 'DECREASING') return '\u2193'
  return '\u2192'
}

function trendColor(trend: string, cls: string): string {
  if (trend === 'INCREASING') return cls !== 'NO_DRIFT' ? 'text-gov-red' : 'text-gov-green'
  if (trend === 'DECREASING') return 'text-gov-green'
  return 'text-muted'
}

function FeatureRow({ entry }: { entry: PSIFeatureEntry }) {
  return (
    <div className="grid grid-cols-[1fr_auto_auto] gap-x-2 gap-y-0.5 text-2xs font-mono items-center">
      <span className="text-primary truncate">{entry.feature}</span>

      <span className={`text-right tabular-nums ${psiColor(entry.classification)}`}>
        {entry.psi.toFixed(4)}
      </span>

      <div className="flex items-center gap-1">
        <span
          className={`text-2xs font-bold px-1.5 py-0.5 rounded border ${psiBg(entry.classification)}`}
        >
          {entry.classification.replace(/_/g, ' ')}
        </span>
        <span className={`text-2xs w-3 text-center ${trendColor(entry.trend, entry.classification)}`}>
          {trendArrow(entry.trend, entry.classification)}
        </span>
      </div>
    </div>
  )
}

function AssetDriftSection({ asset, status }: { asset: string; status: PSIAssetStatus }) {
  const sortedFeatures = useMemo(
    () => [...status.per_feature].sort((a, b) => b.psi - a.psi),
    [status.per_feature],
  )

  return (
    <div className="bg-panel/80 border border-default rounded-lg px-3 py-2.5 text-[11px] text-secondary hover:border-strong/80 transition-colors">
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-primary font-mono">{asset}</span>
          {!status.psi_ok && (
            <span className="text-2xs font-bold text-gov-red bg-gov-red-muted px-1.5 py-0.5 rounded border border-gov-red/20">
              PSI HALT
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <span className={`text-2xs font-bold px-1.5 py-0.5 rounded border ${psiBg(status.worst_classification)}`}>
            {status.worst_classification.replace(/_/g, ' ')}
          </span>
          <span className="text-tertiary font-mono text-2xs">
            {status.moderate_count > 0 ? `${status.moderate_count} mod ` : ''}
            {status.severe_count > 0 ? `${status.severe_count} sev` : ''}
          </span>
        </div>
      </div>

      <div className="space-y-1">
        {sortedFeatures.map(entry => (
          <FeatureRow key={entry.feature} entry={entry} />
        ))}
      </div>
    </div>
  )
}

function PSISkeleton() {
  return (
    <div className="bg-panel/80 border border-default rounded-lg px-3 py-2.5 animate-pulse">
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="h-4 w-16 bg-panel rounded" />
        <div className="h-3 w-20 bg-panel rounded" />
      </div>
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="h-3 bg-panel rounded mb-1" />
      ))}
    </div>
  )
}

export default function PSIDriftCard() {
  const { data, isPending, isError, error } = usePSI()

  if (isPending) {
    return (
      <Panel className="p-4">
        <SectionHeader title="PSI Drift" accent="amber" />
        <div className="grid grid-cols-1 gap-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <PSISkeleton key={i} />
          ))}
        </div>
      </Panel>
    )
  }

  if (isError) {
    return (
      <Panel className="p-4">
        <SectionHeader title="PSI Drift" accent="amber" />
        <div className="flex flex-col items-center justify-center py-6 gap-2">
          <span className="text-xs text-gov-red/80">Failed to load PSI drift data</span>
          <span className="text-2xs text-muted font-mono">{error?.message}</span>
        </div>
      </Panel>
    )
  }

  if (!data) return null

  const entries = Object.entries(data).sort(([a], [b]) => a.localeCompare(b))

  const halted = entries.filter(([, s]) => !s.psi_ok)
  const active = entries.filter(([, s]) => s.psi_ok)

  return (
    <Panel className="p-4">
      <SectionHeader
        title="PSI Drift"
        accent="amber"
        meta={
          <span className="text-[10px] text-tertiary font-mono bg-panel px-2 py-0.5 rounded border border-default tabular-nums">
            {active.length} ok · {halted.length} halted
          </span>
        }
      />

      <div className="grid grid-cols-1 gap-2">
        {active.map(([name, status]) => (
          <AssetDriftSection key={name} asset={name} status={status} />
        ))}
      </div>

      {halted.length > 0 && (
        <details className="mt-3 group">
          <summary className="cursor-pointer text-[11px] text-tertiary font-mono px-2 py-1.5 rounded-md hover:bg-panel hover:text-secondary transition-colors select-none list-none flex items-center gap-1">
            <span className="text-muted group-open:rotate-90 transition-transform inline-block">▸</span>
            {halted.length} halted asset{halted.length > 1 ? 's' : ''}
          </summary>
          <div className="grid grid-cols-1 gap-2 mt-2">
            {halted.map(([name, status]) => (
              <AssetDriftSection key={name} asset={name} status={status} />
            ))}
          </div>
        </details>
      )}
    </Panel>
  )
}
