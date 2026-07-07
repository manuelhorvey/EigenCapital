import { useMemo } from 'react'
import { Activity } from 'lucide-react'
import { useWalTimeline, groupWalEvents } from '../hooks/useWalTimeline'
import type { WalEvent } from '../hooks/useWalTimeline'
import { formatTimeAgo } from '../utils/format'

interface Props {
  assetName: string
}

function ProbaBar({ probLong, probShort, probNeutral }: { probLong: number; probShort: number; probNeutral: number }) {
  const total = probLong + probShort + probNeutral
  if (total === 0) return null
  const l = (probLong / total) * 100
  const s = (probShort / total) * 100
  const n = (probNeutral / total) * 100
  return (
    <div className="w-full h-1.5 bg-panel rounded-full overflow-hidden flex">
      <div className="h-full transition-all" style={{ width: `${l}%`, backgroundColor: 'var(--color-gov-green, #22c55e)' }} />
      <div className="h-full transition-all" style={{ width: `${n}%`, backgroundColor: 'var(--color-gov-init, #64748b)' }} />
      <div className="h-full transition-all" style={{ width: `${s}%`, backgroundColor: 'var(--color-gov-red, #ef4444)' }} />
    </div>
  )
}

function GateBadge({ name, passed }: { name: string; passed: boolean }) {
  return (
    <span className={`inline-flex text-[10px] font-mono font-medium px-1 py-[1px] rounded-sm ${
      passed ? 'text-gov-green bg-gov-green-muted' : 'text-gov-red bg-gov-red-muted'
    }`}>
      {name}
    </span>
  )
}

function extractSignal(events: WalEvent[]): string | null {
  for (const ev of events) {
    if (ev.event_type === 'decision_output') {
      return (ev.payload.final_signal as string) ?? null
    }
  }
  return null
}

function extractProbas(events: WalEvent[]): { probLong: number; probShort: number; probNeutral: number } | null {
  for (const ev of events) {
    if (ev.event_type === 'inference_output') {
      return {
        probLong: (ev.payload.prob_long as number) ?? 0,
        probShort: (ev.payload.prob_short as number) ?? 0,
        probNeutral: (ev.payload.prob_neutral as number) ?? 0,
      }
    }
  }
  return null
}

function extractGates(events: WalEvent[]): { gatesAborted: boolean } | null {
  for (const ev of events) {
    if (ev.event_type === 'decision_output') {
      return { gatesAborted: (ev.payload.gates_aborted as boolean) ?? false }
    }
  }
  return null
}

function extractGatesTrace(events: WalEvent[]): Record<string, boolean> | null {
  for (const ev of events) {
    if (ev.event_type === 'decision_output') {
      return (ev.payload.gates_trace as Record<string, boolean>) ?? null
    }
  }
  return null
}

function WalCard({ group }: { group: ReturnType<typeof groupWalEvents>[number] }) {
  const signal = extractSignal(group.events)
  const probas = extractProbas(group.events)
  const gates = extractGates(group.events)
  const gatesTrace = extractGatesTrace(group.events)

  return (
    <div className="rounded-lg border border-default bg-panel p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-2xs font-mono text-tertiary truncate" title={group.featureHash}>
            {group.featureHash.slice(0, 12)}
          </span>
          <span className="text-2xs text-tertiary">{formatTimeAgo(group.ts)}</span>
        </div>
        <span className={`text-xs font-bold font-mono ${
          signal === 'BUY' ? 'text-gov-green' : signal === 'SELL' ? 'text-gov-red' : 'text-tertiary'
        }`}>
          {signal ?? '—'}
        </span>
      </div>

      {probas && <ProbaBar {...probas} />}

      {gatesTrace && Object.keys(gatesTrace).length > 0 && (
        <div className="flex flex-wrap gap-1">
          {Object.entries(gatesTrace).map(([name, passed]) => (
            <GateBadge key={name} name={name.replace(/_/g, ' ')} passed={passed} />
          ))}
        </div>
      )}

      {gates !== null && gates.gatesAborted && (
        <div className="text-2xs font-medium text-gov-red">ABORTED</div>
      )}
    </div>
  )
}

/** Write-Ahead Log timeline for a single asset, showing inference and decision events grouped by cycle.
 * @param {object} props
 * @param {string} props.assetName - Asset symbol to load WAL events for */
export default function WalTimeline({ assetName }: Props) {
  const { data, isLoading, isError } = useWalTimeline(assetName)

  const groups = useMemo(() => {
    if (!data?.events) return []
    return groupWalEvents(data.events)
  }, [data])

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-8 justify-center text-tertiary">
        <Activity className="w-4 h-4 animate-pulse" strokeWidth={1.5} />
        <span className="text-xs">Loading WAL...</span>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="text-xs text-gov-red py-4 text-center">Failed to load WAL timeline</div>
    )
  }

  if (groups.length === 0) {
    return (
      <div className="text-xs text-tertiary py-4 text-center">No WAL events for {assetName}</div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="text-2xs text-tertiary font-mono">{data?.total ?? 0} events · {groups.length} cycles</div>
      {groups.slice(0, 50).map(g => (
        <WalCard key={g.featureHash} group={g} />
      ))}
    </div>
  )
}