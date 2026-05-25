import React, { useMemo } from 'react'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import { useGovernance } from '../hooks/useGovernance'
import type { GovernanceState } from '../hooks/useGovernance'

function scalarColor(value: number): string {
  if (value >= 1.0) return 'text-gov-green'
  if (value > 0.70) return 'text-gov-yellow'
  return 'text-gov-red'
}

function sizeColor(value: number): string {
  if (value >= 1.0) return 'text-gov-green'
  if (value > 0.70) return 'text-gov-yellow'
  return 'text-gov-red'
}

function regimeColor(regime: string): string {
  switch (regime) {
    case 'STRESSED':
      return 'text-gov-red'
    case 'THIN':
      return 'text-gov-yellow'
    default:
      return 'text-gov-green'
  }
}

function narrRegimeColor(regime: string | null): string {
  if (!regime) return 'text-muted'
  if (regime === 'risk_off') return 'text-gov-red'
  if (regime === 'geopol_tension') return 'text-gov-yellow'
  if (regime === 'risk_on') return 'text-gov-green'
  return 'text-secondary'
}

function Dot({ color }: { color: string }) {
  return <span className={`w-1.5 h-1.5 rounded-full inline-block shrink-0 ${color}`} />
}

function validityStateColor(state: string): string {
  if (state === 'GREEN' || state === 'green') return 'text-gov-green bg-gov-green-muted border-gov-green/20'
  if (state === 'YELLOW' || state === 'yellow' || state === 'amber') return 'text-gov-yellow bg-gov-yellow-muted border-gov-yellow/20'
  if (state === 'RED' || state === 'red') return 'text-gov-red bg-gov-red-muted border-gov-red/20'
  return 'text-gov-init bg-gov-init-muted border-gov-init/20'
}

function GovernanceStateCard({
  asset,
  state,
}: {
  asset: string
  state: GovernanceState
}) {
  const rows: { label: string; sl: number; size: number; slColor: string; sizeColor: string }[] = useMemo(
    () => [
      {
        label: 'Regime',
        sl: state.regime_sl_mult,
        size: state.regime_size_scalar,
        slColor: scalarColor(state.regime_sl_mult),
        sizeColor: sizeColor(state.regime_size_scalar),
      },
      {
        label: 'Narrative',
        sl: state.narrative_sl_mult,
        size: state.narrative_size_scalar,
        slColor: scalarColor(state.narrative_sl_mult),
        sizeColor: sizeColor(state.narrative_size_scalar),
      },
      {
        label: 'Liquidity',
        sl: state.liquidity_sl_mult,
        size: state.liquidity_size_scalar,
        slColor: scalarColor(state.liquidity_sl_mult),
        sizeColor: sizeColor(state.liquidity_size_scalar),
      },
      {
        label: 'Combined',
        sl: state.combined_sl_mult,
        size: state.combined_size_scalar,
        slColor: scalarColor(state.combined_sl_mult),
        sizeColor: sizeColor(state.combined_size_scalar),
      },
    ],
    [state],
  )

  return (
    <div className={`bg-panel/80 border rounded-lg px-3 py-2.5 text-[11px] text-secondary hover:border-strong/80 transition-colors ${state.halted ? 'border-l-2 border-l-gov-red border-default' : 'border-default'}`}>
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-primary font-mono">{asset}</span>
          <span className={`text-2xs font-bold px-1.5 py-0.5 rounded border ${validityStateColor(state.validity_state)}`}>
            {state.validity_state}
          </span>
          {state.halted && (
            <span className="flex items-center gap-1 text-2xs font-bold text-gov-red bg-gov-red-muted px-1.5 py-0.5 rounded border border-gov-red/20" title="Trading halted by governance rules">
              <span className="w-1.5 h-1.5 rounded-full bg-gov-red state-pulse-red" />
              HALTED
            </span>
          )}
          {state.floor_active && (
            <span className="text-2xs font-bold text-gov-yellow bg-gov-yellow-muted px-1.5 py-0.5 rounded border border-gov-yellow/20" title="Size scalar floored at 0.30x">
              FLOOR
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <Dot color={regimeColor(state.liquidity_regime)} />
          <span className="text-tertiary font-mono text-2xs">{state.liquidity_regime}</span>
          {state.narrative_regime && (
            <>
              <Dot color={narrRegimeColor(state.narrative_regime)} />
              <span className="text-tertiary font-mono text-2xs">{state.narrative_regime.replace(/_/g, ' ')}</span>
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-1 text-2xs font-mono">
        <span className="text-tertiary font-sans" />
        <span className="text-tertiary text-center">SL</span>
        <span className="text-tertiary text-center">Size</span>

        {rows.map(r => (
          <React.Fragment key={r.label}>
            <span className="text-tertiary font-sans">{r.label}</span>
            <span className={`text-center ${r.slColor}`}>{r.sl.toFixed(2)}x</span>
            <span className={`text-center ${r.sizeColor}`}>{r.size.toFixed(2)}x</span>
          </React.Fragment>
        ))}
      </div>
    </div>
  )
}

function GovernanceCardSkeleton() {
  return (
    <div className="bg-panel/80 border border-default rounded-lg px-3 py-2.5 animate-pulse">
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="h-4 w-16 bg-panel rounded" />
        <div className="h-3 w-20 bg-panel rounded" />
      </div>
      <div className="grid grid-cols-3 gap-1">
        {Array.from({ length: 12 }).map((_, i) => (
          <div key={i} className="h-3 bg-panel rounded" />
        ))}
      </div>
    </div>
  )
}

export default function GovernanceStateCards() {
  const { data, isPending, isError, error } = useGovernance()

  if (isPending) {
    return (
      <Panel className="p-4">
        <SectionHeader title="Governance State" accent="indigo" />
        <div className="grid grid-cols-1 gap-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <GovernanceCardSkeleton key={i} />
          ))}
        </div>
      </Panel>
    )
  }

  if (isError) {
    return (
      <Panel className="p-4">
        <SectionHeader title="Governance State" accent="indigo" />
        <div className="flex flex-col items-center justify-center py-6 gap-2">
          <span className="text-xs text-gov-red/80">Failed to load governance data</span>
          <span className="text-2xs text-muted font-mono">{error?.message}</span>
        </div>
      </Panel>
    )
  }

  if (!data) return null

  const entries = Object.entries(data).sort(([a], [b]) => a.localeCompare(b))

  const halted = entries.filter(([, s]) => s.halted)
  const active = entries.filter(([, s]) => !s.halted)

  return (
    <Panel className="p-4">
      <SectionHeader
        title="Governance State"
        accent="indigo"
        meta={
          <span className="text-[10px] text-tertiary font-mono bg-panel px-2 py-0.5 rounded border border-default tabular-nums">
            {active.length} active · {halted.length} halted
          </span>
        }
      />

      <div className="grid grid-cols-1 gap-2">
        {active.map(([name, state]) => (
          <GovernanceStateCard key={name} asset={name} state={state} />
        ))}
      </div>

      {halted.length > 0 && (
        <details className="mt-3 group">
          <summary className="cursor-pointer text-[11px] text-tertiary font-mono px-2 py-1.5 rounded-md hover:bg-panel hover:text-secondary transition-colors select-none list-none flex items-center gap-1">
            <span className="text-muted group-open:rotate-90 transition-transform inline-block">▸</span>
            {halted.length} halted asset{halted.length > 1 ? 's' : ''}
          </summary>
          <div className="grid grid-cols-1 gap-2 mt-2">
            {halted.map(([name, state]) => (
              <GovernanceStateCard key={name} asset={name} state={state} />
            ))}
          </div>
        </details>
      )}
    </Panel>
  )
}
