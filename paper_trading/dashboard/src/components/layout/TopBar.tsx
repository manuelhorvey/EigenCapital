import { memo, useCallback, useMemo, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { LayoutDashboard, Zap, BarChart3, Shield, RefreshCw, Menu, Bell } from 'lucide-react'
import { useSidebarBadges } from '../../hooks/useSidebarBadges'
import { useSystemSnapshot } from '../../hooks/useSystemSnapshot'
import { useEngineHealth } from '../../hooks/useEngineHealth'
import { systemSelectors } from '../../selectors/system'
import ThemeToggle from '../ThemeToggle'
import { useNotificationCenter } from '../../hooks/useNotificationCenter'

// ── Tab Definitions ─────────────────────────────────────────────

interface TabItem {
  to: string
  label: string
  icon: React.ReactNode
  badgeKey?: 'trading' | 'risk'
}

const TABS: TabItem[] = [
  { to: '/', label: 'Dashboard', icon: <LayoutDashboard className="w-3.5 h-3.5" strokeWidth={1.5} /> },
  { to: '/trading', label: 'Trading', icon: <Zap className="w-3.5 h-3.5" strokeWidth={1.5} />, badgeKey: 'trading' },
  { to: '/execution', label: 'Execution', icon: <BarChart3 className="w-3.5 h-3.5" strokeWidth={1.5} /> },
  { to: '/risk', label: 'Risk', icon: <Shield className="w-3.5 h-3.5" strokeWidth={1.5} />, badgeKey: 'risk' },
]

// ── Ticker token helpers ────────────────────────────────────────

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
}

function TopBarInner({ onToggleSidebar, onToggleNotifications }: TopBarProps) {
  const badges = useSidebarBadges()
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
      className={`relative min-h-[52px] w-full flex items-center gap-1 px-2 sm:px-3 border-b border-default text-xs font-mono tabular-nums overflow-hidden shrink-0 ${
        parts.halted ? 'bg-gov-red/10 border-gov-red/20' : 'bg-app/95'
      }`}
      aria-label="Top bar"
    >
      {/* Left: Navigation tabs — hidden on mobile (< lg), shown on desktop.
          Mobile gets a separate TabBar row below the TopBar instead. */}
      <nav className="hidden lg:flex items-center gap-0.5 shrink-0" aria-label="Main tabs">
        {TABS.map((tab) => {
          const badge = tab.badgeKey ? badges[tab.badgeKey] : undefined
          return (
            <NavLink
              key={tab.to}
              to={tab.to}
              end
              aria-label={tab.label}
              className={({ isActive }) =>
                `flex items-center gap-1 px-1.5 sm:px-2 py-1.5 text-2xs sm:text-xs font-medium rounded-md transition-colors shrink-0 ${
                  isActive
                    ? 'bg-accent-emerald/8 text-accent-emerald'
                    : 'text-tertiary hover:text-secondary hover:bg-panel/60'
                } active:scale-95`
              }
            >
              {tab.icon}
              <span className="hidden sm:inline ml-0.5">{tab.label}</span>
              {badge != null && badge > 0 && (
                <span className="inline-flex items-center justify-center min-w-[14px] h-3.5 px-1 rounded-full text-[8px] font-bold leading-none bg-gov-red-muted text-gov-red border border-gov-red/25">
                  {badge}
                </span>
              )}
            </NavLink>
          )
        })}
      </nav>

      {/* Center: Pinned halted asset badges */}
      {haltedAssets.length > 0 && (
        <div className="flex items-center gap-1 overflow-hidden">
          {haltedAssets.map(name => (
            <span
              key={name}
              className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-gov-red/10 border border-gov-red/25 text-2xs font-semibold text-gov-red shrink-0"
            >
              <span className="w-1 h-1 rounded-full bg-gov-red" />
              {name}
            </span>
          ))}
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
          <ThemeToggle />
          <button
            type="button"
            onClick={onToggleNotifications}
            className="relative min-h-[44px] min-w-[44px] inline-flex items-center justify-center rounded text-tertiary hover:text-primary active:scale-[0.97] focus-ring transition-colors"
            aria-label={`Notifications${unreadCount > 0 ? ` (${unreadCount} unread)` : ''}`}
          >
            <Bell className="w-3 h-3" strokeWidth={2} />
            {unreadCount > 0 && (
              <span className="absolute -top-0.5 -right-0.5 min-w-[14px] h-3.5 px-1 rounded-full text-[7px] font-bold leading-none bg-gov-red text-white flex items-center justify-center shadow-sm">
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
            <RefreshCw className={`w-3 h-3 ${refreshing ? 'animate-spin' : ''}`} strokeWidth={2} />
          </button>
          <button
            type="button"
            onClick={onToggleSidebar}
            className="lg:hidden min-h-[44px] min-w-[44px] inline-flex items-center justify-center rounded text-tertiary hover:text-primary active:scale-[0.97] focus-ring transition-colors"
            aria-label="Open navigation"
          >
            <Menu className="w-3 h-3" strokeWidth={2} />
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * Single-row top bar merging navigation tabs + status ticker tokens + controls.
 * Replaces the separate TickerRail + TabBar pattern, saving ~24px vertical space.
 */
const TopBar = memo(TopBarInner)
TopBar.displayName = 'TopBar'
export default TopBar
