import { useMemo } from 'react'
import { useSystemSnapshot } from '../../hooks/useSystemSnapshot'
import { useEngineHealth } from '../../hooks/useEngineHealth'
import { systemSelectors } from '../../selectors/system'

/**
 * TickerRail — operator-console signature element.
 *
 * A 32px-tall mono breadcrumb pinned above <Header>. Reads as a single
 * continuous string of facts the operator needs at every glance:
 *   seq id · engine state · last tick latency · cycle · intake/admit ·
 *   halt state · asset count
 *
 * One fact per word. A field turning negative replaces its word with a
 * coloured token rather than restructuring the rail. When the engine
 * halts the entire rail renders an inline halt-because-word.
 */
export default function TickerRail() {
  const { data: snapshot } = useSystemSnapshot(systemSelectors.snapshot)
  const health = useEngineHealth()

  const parts = useMemo(() => {
    const now = Date.now()
    const lastUpdateMs = snapshot?.engine_status?.last_update
      ? Date.parse(snapshot.engine_status.last_update)
      : null
    const tickAgoSec = lastUpdateMs != null ? Math.max(0, Math.round((now - lastUpdateMs) / 1000)) : null

    const engineState = health.isError
      ? ('dead' as const)
      : health.isLoading || health.data == null
        ? null
        : health.data.engine_alive
          ? ('alive' as const)
          : ('stale' as const)

    const seqId = snapshot?.sequence_id
    const admission = snapshot?.portfolio?.admission
    const halted = Boolean(snapshot?.emergency_halt)
    const haltReason = snapshot?.halt_reason ?? snapshot?.halt_detail
    const assetCount = snapshot?.assets ? Object.keys(snapshot.assets).length : null

    const tokens: Array<{ label: string; value: string; tone?: 'good' | 'warn' | 'bad' | 'muted' }> = []

    tokens.push({ label: 'Q', value: '·QUORRIN', tone: 'muted' })
    if (seqId != null) tokens.push({ label: 'seq', value: `#${seqId}` })
    if (engineState) {
      const tone = engineState === 'alive' ? 'good' : engineState === 'stale' ? 'warn' : 'bad'
      tokens.push({ label: 'engine', value: engineState, tone })
    }
    if (tickAgoSec != null) {
      const tone = tickAgoSec <= 30 ? 'good' : tickAgoSec <= 120 ? 'warn' : 'bad'
      tokens.push({ label: 'tick', value: `${tickAgoSec}s`, tone })
    }
    if (admission && admission.n_intents > 0) {
      tokens.push({
        label: 'pek',
        value: `${admission.n_admitted}/${admission.n_intents}`,
        tone: admission.n_rejected > 0 ? 'warn' : 'good',
      })
    }
    if (halted) {
      tokens.push({ label: 'halt', value: 'YES', tone: 'bad' })
    } else {
      tokens.push({ label: 'halt', value: 'no', tone: 'muted' })
    }
    if (assetCount != null) tokens.push({ label: 'assets', value: String(assetCount) })

    return { tokens, haltReason, halted }
  }, [snapshot, health.isError, health.isLoading, health.data])

  if (parts.halted && parts.haltReason) {
    return (
      <div className="h-8 w-full px-2 sm:px-4 flex items-center gap-3 text-xs font-mono tabular-nums border-b border-default bg-gov-red/15 text-gov-red">
        <span className="font-bold">HALT</span>
        <span className="truncate">— {parts.haltReason}</span>
        <span className="ml-auto opacity-70">engine halted · all positions frozen</span>
      </div>
    )
  }

  return (
    <div className="h-8 w-full px-2 sm:px-4 flex items-center gap-3 text-xs font-mono tabular-nums border-b border-default bg-app/80 text-tertiary overflow-x-auto whitespace-nowrap">
      {parts.tokens.map((t, i) => {
        const cls =
          t.tone === 'good' ? 'text-gov-green'
          : t.tone === 'warn' ? 'text-gov-yellow'
          : t.tone === 'bad'  ? 'text-gov-red'
          : 'text-tertiary'
        return (
          <span key={`${t.label}-${i}`} className="inline-flex items-center gap-1.5">
            <span className="uppercase tracking-wider text-muted/70">{t.label}</span>
            <span className={`font-semibold ${cls}`}>{t.value}</span>
            {i < parts.tokens.length - 1 && <span className="text-muted/40">·</span>}
          </span>
        )
      })}
    </div>
  )
}
