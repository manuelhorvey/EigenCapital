import { useCallback, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Menu } from 'lucide-react'
import { useSystemSnapshot } from '../../hooks/useSystemSnapshot'
import { useEngineHealth } from '../../hooks/useEngineHealth'
import { systemSelectors } from '../../selectors/system'

/**
 * TickerRail — operator-console signature element.
 *
 * A 32px-tall mono breadcrumb pinned above the page content. Reads as
 * one continuous string of facts the operator needs on every glance:
 *   seq · engine · last tick · pek · halt · assets · mt5
 *
 * One fact per word. A field turning negative replaces its word with
 * a coloured token rather than restructuring the rail. When the
 * engine halts the entire rail renders an inline halt-because-word.
 *
 * Existing Affordances (Phase 8.1, Phase 9, Phase D-* additions):
 *   - read-only state tokens (colour-coded by tone, mono, h-8)
 *   - responsive: tokens wrap naturally below the sm breakpoint
 *     instead of horizontal-scrolling; the trailing cluster of
 *     controls is anchored to the right end via `ml-auto`
 *   - trailing cluster (right end, ml-auto):
 *       - refresh glyph: always rendered, click→React Query
 *         invalidate (full data refresh)
 *       - menu glyph: rendered only on mobile (< lg); on desktop
 *         the Sidebar is persistent so the menu trigger would be
 *         noise. Click→opens the off-canvas Sidebar.
 *
 * The first top-bar (Header) was deleted in Phase D-12 alongside this
 * extension. Previous Header contents (brand wordmark, seq#, engine
 * state, MT5 status) were already folded into the rail in Phase D-9;
 * Header had collapsed to two icon-only buttons — menu and refresh —
 * which this commit moves into the rail itself.
 */
type TokenTone = 'good' | 'warn' | 'bad' | 'muted'

interface RailToken {
  label: string
  value: string
  tone?: TokenTone
}

function toneClass(tone?: TokenTone): string {
  switch (tone) {
    case 'good': return 'text-gov-green'
    case 'warn': return 'text-gov-yellow'
    case 'bad':  return 'text-gov-red'
    default:     return 'text-tertiary'
  }
}

function classifyMt5(state: string, equity: number | null): { value: string; tone: TokenTone } {
  if (state === 'ERROR') return { value: 'ERROR', tone: 'bad' }
  if (state === 'CONNECTED') {
    return { value: equity != null ? `live $${equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : 'live', tone: 'good' }
  }
  if (state === 'DISCONNECTED') return { value: 'disc', tone: 'warn' }
  return { value: 'unknown', tone: 'muted' }
}

interface TickerRailProps {
  /** Toggle the off-canvas Sidebar. Required on mobile where the
   *  menu glyph is rendered; ignored on desktop where the menu
   *  glyph is hidden because the persistent Sidebar is already
   *  visible. Always passed by AppShell. */
  onToggleSidebar?: () => void
}

export default function TickerRail({ onToggleSidebar }: TickerRailProps) {
  const { data: snapshot }   = useSystemSnapshot(systemSelectors.snapshot)
  const { data: mt5Live }    = useSystemSnapshot(systemSelectors.mt5)
  const health = useEngineHealth()
  const queryClient = useQueryClient()

  const [refreshing, setRefreshing] = useState(false)
  const handleRefresh = useCallback(async () => {
    if (refreshing) return
    setRefreshing(true)
    try {
      await queryClient.invalidateQueries()
    } finally {
      // The cache invalidation is fast, but the React Query refetch
      // itself takes a tick; gate the spinner-visible window at a
      // minimum so the operator actually perceives the feedback.
      setTimeout(() => setRefreshing(false), 600)
    }
  }, [queryClient, refreshing])

  const parts = useMemo(() => {
    const now = Date.now()
    const lastUpdateMs = snapshot?.engine_status?.last_update
      ? Date.parse(snapshot.engine_status.last_update)
      : null
    const tickAgoSec = lastUpdateMs != null
      ? Math.max(0, Math.round((now - lastUpdateMs) / 1000))
      : null

    const engineState: 'alive' | 'stale' | 'dead' | null = health.isError
      ? 'dead'
      : (health.isLoading || health.data == null)
        ? null
        : health.data.engine_alive
          ? 'alive'
          : 'stale'

    const seqId      = snapshot?.sequence_id
    const admission  = snapshot?.portfolio?.admission
    const halted     = Boolean(snapshot?.emergency_halt)
    const haltReason = snapshot?.halt_reason ?? snapshot?.halt_detail
    const assetCount = snapshot?.assets ? Object.keys(snapshot.assets).length : null

    const mt5State = mt5Live?.status ?? 'UNKNOWN'
    const mt5Equity = mt5Live?.account?.portfolio_value != null
      ? Number(mt5Live.account.portfolio_value)
      : null

    const tokens: RailToken[] = []
    tokens.push({ label: 'Q', value: '·QUORRIN', tone: 'muted' })
    if (seqId != null) tokens.push({ label: 'seq', value: `#${seqId}` })
    if (engineState) {
      tokens.push({
        label: 'engine',
        value: engineState,
        tone: engineState === 'alive' ? 'good'
            : engineState === 'stale' ? 'warn'
            : 'bad',
      })
    }
    if (tickAgoSec != null) {
      tokens.push({
        label: 'tick',
        value: `${tickAgoSec}s`,
        tone: tickAgoSec <= 30 ? 'good' : tickAgoSec <= 120 ? 'warn' : 'bad',
      })
    }
    if (admission && admission.n_intents > 0) {
      tokens.push({
        label: 'pek',
        value: `${admission.n_admitted}/${admission.n_intents}`,
        tone: admission.n_rejected > 0 ? 'warn' : 'good',
      })
    }
    {
      const { value, tone } = classifyMt5(mt5State, mt5Equity)
      tokens.push({ label: 'mt5', value, tone })
    }
    if (halted) {
      tokens.push({ label: 'halt', value: 'YES', tone: 'bad' })
    } else {
      tokens.push({ label: 'halt', value: 'no', tone: 'muted' })
    }
    if (assetCount != null) tokens.push({ label: 'assets', value: String(assetCount) })

    return { tokens, haltReason, halted }
  }, [snapshot, health.isError, health.isLoading, health.data, mt5Live])

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
    <div className="min-h-8 w-full px-2 sm:px-4 py-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-mono tabular-nums border-b border-default bg-app/80 text-tertiary">
      {parts.tokens.map((t, i) => (
        <span key={`${t.label}-${i}`} className="inline-flex items-center gap-1.5">
          <span className="uppercase tracking-wider text-muted/70">{t.label}</span>
          <span className={`font-semibold ${toneClass(t.tone)}`}>{t.value}</span>
          {i < parts.tokens.length - 1 && <span className="text-muted/40" aria-hidden>·</span>}
        </span>
      ))}

      {/* Trailing control cluster — pinned to the right at all
          viewports. Refresh always; menu only on mobile (lg:hidden)
          so the desktop gets no spurious open-sidebar button while
          the persistent Sidebar is already on-screen. */}
      <div className="ml-auto flex items-center gap-2 sm:gap-3">
        <button
          type="button"
          onClick={handleRefresh}
          disabled={refreshing}
          className="min-h-[28px] min-w-[28px] inline-flex items-center justify-center rounded text-tertiary hover:text-primary active:scale-[0.97] focus-ring transition-colors"
          title="Refresh dashboard data"
          aria-label="Refresh dashboard data"
        >
          <RefreshCw
            className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`}
            strokeWidth={2}
          />
        </button>
        <button
          type="button"
          onClick={onToggleSidebar}
          className="lg:hidden min-h-[28px] min-w-[28px] inline-flex items-center justify-center rounded text-tertiary hover:text-primary active:scale-[0.97] focus-ring transition-colors"
          title="Open navigation"
          aria-label="Open navigation"
        >
          <Menu className="w-3.5 h-3.5" strokeWidth={2} />
        </button>
      </div>
    </div>
  )
}
