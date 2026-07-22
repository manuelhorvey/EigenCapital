import { memo, useCallback, useMemo, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Menu, Bell, Command } from 'lucide-react'
import { useSystemSnapshot } from '../../hooks/useSystemSnapshot'
import { useEngineHealth } from '../../hooks/useEngineHealth'
import { systemSelectors } from '../../selectors/system'
import ThemeToggle from '../ThemeToggle'
import { useNotificationCenter } from '../../hooks/useNotificationCenter'

// ── Page title map for context-aware breadcrumb ────────────────
const PAGE_TITLES: Record<string, { label: string; subtitle: string }> = {
  '/': { label: 'Command Center', subtitle: 'System overview & positions' },
  '/trading': { label: 'Trading', subtitle: 'Signals, fills, open trades' },
  '/analytics': { label: 'Analytics', subtitle: 'Performance & attribution' },
  '/risk': { label: 'Governance & Risk', subtitle: 'Health & constraints' },
  '/reports': { label: 'Reports', subtitle: 'Downloads & audit log' },
  '/settings': { label: 'Settings', subtitle: 'Preferences & API keys' },
  '/provenance': { label: 'Provenance', subtitle: 'Decision history & audit trail' },
  '/counterfactual': { label: 'Counterfactual', subtitle: 'What-if scenario analysis' },
}

// ── Ticker token helpers ────────────────────────────────────────

type TokenTone = 'good' | 'warn' | 'bad' | 'muted'

interface RailToken {
  label: string
  value: string
  tone?: TokenTone
}

function toneClass(tone?: TokenTone): string {
  switch (tone) {
    case 'good': return 'text-signal-long'
    case 'warn': return 'text-signal-warn'
    case 'bad':  return 'text-signal-short'
    default:     return 'text-tertiary'
  }
}

function classifyMt5(state: string, equity: number | null): { value: string; tone: TokenTone } {
  if (state === 'ERROR') return { value: 'ERROR', tone: 'bad' }
  if (state === 'CONNECTED') {
    const isBelowFloor = equity != null && equity < 1_000
    const suffix = isBelowFloor ? ' (≤1K)' : ''
    return {
      value: equity != null ? `$${equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}${suffix}` : 'live',
      tone: isBelowFloor ? 'warn' : 'good',
    }
  }
  if (state === 'DISCONNECTED') return { value: 'disc', tone: 'warn' }
  return { value: 'unknown', tone: 'muted' }
}

// ── Halted asset detection ──────────────────────────────────────

function getHaltedAssets(assets: Record<string, { halt?: { halted?: boolean } }> | null | undefined): string[] {
  if (!assets) return []
  return Object.entries(assets)
    .filter(([_, a]) => a?.halt?.halted)
    .map(([name]) => name)
    .sort()
}

// ── Component ───────────────────────────────────────────────────

interface TopBarProps {
  onToggleSidebar?: () => void
  onToggleNotifications?: () => void
  /** Optional: set of renderable sections for context-aware actions */
  contextActions?: React.ReactNode
}

function TopBarInner({ onToggleSidebar, onToggleNotifications, contextActions }: TopBarProps) {
  const location = useLocation()
  const health = useEngineHealth()
  const queryClient = useQueryClient()
  const { data: engStatus } = useSystemSnapshot(systemSelectors.engineStatus)
  const { data: portfolio } = useSystemSnapshot(systemSelectors.portfolio)
  const { data: assets }    = useSystemSnapshot(systemSelectors.assets)
  const { data: snapshot }  = useSystemSnapshot(systemSelectors.snapshot)
  const { data: mt5Live }   = useSystemSnapshot(systemSelectors.mt5)

  const [refreshing, setRefreshing] = useState(false)
  const handleRefresh = useCallback(async () => {
    if (refreshing) return
    setRefreshing(true)
    try {
      await queryClient.invalidateQueries()
    } finally {
      setTimeout(() => setRefreshing(false), 600)
    }
  }, [queryClient, refreshing])

  // Page context
  const pageInfo = PAGE_TITLES[location.pathname] ?? { label: 'Dashboard', subtitle: '' }

  // Build ticker tokens
  const parts = useMemo(() => {
    const now = Date.now()
    const lastUpdateMs = engStatus?.last_update
      ? Date.parse(engStatus.last_update)
      : null
    const tickAgoSec = lastUpdateMs != null
      ? Math.max(0, Math.round((now - lastUpdateMs) / 1000))
      : null

    const engineState: 'alive' | 'stale' | 'dead' | null = health.isError
      ? 'dead'
      : (health.isLoading || health.data == null)
        ? null
        : health.data.engine_alive ? 'alive' : 'stale'

    const seqId      = snapshot?.sequence_id
    const halted     = Boolean(snapshot?.emergency_halt)
    const assetCount = assets ? Object.keys(assets).length : null
    const mt5State   = mt5Live?.status ?? 'UNKNOWN'
    const mt5Equity  = mt5Live?.account?.portfolio_value != null
      ? Number(mt5Live.account.portfolio_value)
      : null

    const tokens: RailToken[] = [
      { label: 'EC', value: '·EIGENCAPITAL', tone: 'muted' },
    ]
    if (seqId != null) tokens.push({ label: 'seq', value: `#${seqId}` })
    if (engineState) {
      tokens.push({
        label: 'engine',
        value: engineState,
        tone: engineState === 'alive' ? 'good' : engineState === 'stale' ? 'warn' : 'bad',
      })
    }
    if (tickAgoSec != null) {
      tokens.push({
        label: 'tick',
        value: `${tickAgoSec}s`,
        tone: tickAgoSec <= 30 ? 'good' : tickAgoSec <= 120 ? 'warn' : 'bad',
      })
    }
    const { value: mt5Val, tone: mt5Tone } = classifyMt5(mt5State, mt5Equity)
    tokens.push({ label: 'mt5', value: mt5Val, tone: mt5Tone })
    if (halted) {
      tokens.push({ label: 'halt', value: 'YES', tone: 'bad' })
    } else {
      tokens.push({ label: 'halt', value: 'no', tone: 'muted' })
    }
    if (assetCount != null && assetCount > 0) tokens.push({ label: 'assets', value: String(assetCount) })
    return { tokens, halted }
  }, [snapshot, engStatus, portfolio, assets, health, mt5Live])

  // Detect halted assets for pinned alert badges
  const haltedAssets = useMemo(() => getHaltedAssets(assets), [assets])

  // Notification center state
  const { unreadCount } = useNotificationCenter()

  return (
    <div
      aria-live={parts.halted ? 'assertive' : 'polite'}
      className={`relative min-h-[44px] w-full flex items-center gap-1 px-2 sm:px-3 border-b border-default text-xs font-mono tabular-nums overflow-hidden shrink-0 ${
        parts.halted ? 'bg-signal-short/10 border-signal-short/20' : 'bg-app/95'
      }`}
      aria-label="Top bar"
    >
      {/* Left: Sidebar toggle (mobile) + Page context breadcrumb */}
      <button
        type="button"
        onClick={onToggleSidebar}
        className="lg:hidden min-h-[44px] min-w-[44px] inline-flex items-center justify-center rounded text-tertiary hover:text-primary active:scale-[0.97] focus-ring transition-colors shrink-0"
        aria-label="Open navigation"
      >
        <Menu className="w-3.5 h-3.5" strokeWidth={2} />
      </button>

      <div className="hidden lg:flex items-center gap-2 min-w-0 shrink-0">
        <span className="text-sm font-semibold text-primary truncate">{pageInfo.label}</span>
        {pageInfo.subtitle && (
          <span className="text-2xs text-tertiary/60 hidden xl:inline truncate">{pageInfo.subtitle}</span>
        )}
      </div>

      {/* Center: Pinned halted asset badges */}
      {haltedAssets.length > 0 && (
        <div className="flex items-center gap-1 overflow-hidden">
          {haltedAssets.map(name => (
            <span
              key={name}
              className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-signal-short/10 border border-signal-short/25 text-2xs font-semibold text-signal-short shrink-0"
            >
              <span className="w-1 h-1 rounded-full bg-signal-short" />
              {name}
            </span>
          ))}
        </div>
      )}

      {/* Context actions (page-specific controls) */}
      {contextActions && (
        <div className="flex items-center gap-1 overflow-hidden">
          {contextActions}
        </div>
      )}

      {/* Spacer */}
      <div className="flex-1 min-w-2" />

      {/* Right: Ticker tokens + controls */}
      <div className="flex items-center gap-1 sm:gap-1.5 overflow-hidden shrink-0">
        {parts.tokens.map((t, i) => {
          const isCritical = t.label === 'engine' || t.label === 'halt' || t.label === 'mt5'
          return (
            <span key={`${t.label}-${i}`} className={`${isCritical ? 'inline-flex' : 'hidden'} sm:inline-flex items-center gap-1 text-2xs`}>
              <span className="text-tertiary/60">{t.label}</span>
              <span className={`font-semibold ${toneClass(t.tone)}`}>{t.value}</span>
              {i < parts.tokens.length - 1 && <span className="text-muted/30 mx-0.5" aria-hidden>|</span>}
            </span>
          )
        })}

        <div className="flex items-center gap-0.5 ml-1 shrink-0">
          <button
            type="button"
            onClick={() => {
              // Dispatch custom event to open command palette
              window.dispatchEvent(new KeyboardEvent('keydown', { metaKey: true, key: 'k', bubbles: true }))
            }}
            className="hidden sm:inline-flex items-center gap-1 px-2 py-1 rounded-md text-tertiary hover:text-secondary hover:bg-panel/60 border border-transparent hover:border-default transition-colors text-2xs"
            aria-label="Open command palette"
            title="Cmd+K"
          >
            <Command className="w-3 h-3" strokeWidth={1.5} />
            <span className="hidden md:inline">Cmd+K</span>
          </button>
          <ThemeToggle />
          <button
            type="button"
            onClick={onToggleNotifications}
            className="relative min-h-[44px] min-w-[44px] inline-flex items-center justify-center rounded text-tertiary hover:text-primary active:scale-[0.97] focus-ring transition-colors"
            aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ''}`}
          >
            <Bell className="w-3.5 h-3.5" strokeWidth={2} />
            {unreadCount > 0 && (
              <span className="absolute -top-0.5 -right-0.5 min-w-[14px] h-3.5 px-1 rounded-full text-[7px] font-bold leading-none bg-signal-short text-white flex items-center justify-center shadow-sm">
                {unreadCount > 9 ? '9+' : unreadCount}
              </span>
            )}
          </button>
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="min-h-[44px] min-w-[44px] inline-flex items-center justify-center rounded text-tertiary hover:text-primary active:scale-[0.97] focus-ring transition-colors"
            aria-label="Refresh dashboard data"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} strokeWidth={2} />
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * Context-aware top bar with page breadcrumb + ticker tokens + controls.
 * Navigation tabs moved to Sidebar (desktop) and TabBar (mobile).
 * Now takes an optional `contextActions` prop for per-page action buttons.
 */
const TopBar = memo(TopBarInner)
TopBar.displayName = 'TopBar'
export default TopBar
