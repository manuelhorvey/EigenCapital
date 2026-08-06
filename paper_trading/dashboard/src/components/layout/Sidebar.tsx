import { memo, useCallback, useEffect, useRef } from 'react'
import { NavLink } from 'react-router-dom'
import { X, TrendingUp, Search, Command } from 'lucide-react'
import { useEngineHealth } from '../../hooks/useEngineHealth'
import { useSidebarBadges } from '../../hooks/useSidebarBadges'
import { useCommandPalette } from '../../hooks/useCommandPalette'
import { useSystemSnapshot } from '../../hooks/useSystemSnapshot'
import { systemSelectors } from '../../selectors/system'
import { NAV_GROUPS, SIDEBAR_NAV_ITEMS, type NavItem } from '../../lib/navigation'
import Divider from '../ui/Divider'
import { formatTimeAgo } from '../../utils/format'
const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'

interface SidebarProps {
  open: boolean
  onClose: () => void
}

interface NavItemProps {
  item: NavItem
  badge?: number
  onClose: () => void
  onKeyDown: (e: React.KeyboardEvent, id: string) => void
}

const NavItem = memo(function NavItem({ item, badge, onClose, onKeyDown }: NavItemProps) {
  return (
    <NavLink
      id={`nav-${item.id}`}
      to={item.to}
      end
      onClick={onClose}
      onKeyDown={e => onKeyDown(e, item.id)}
      className={({ isActive }) =>
        `w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-xs font-medium
        transition-all duration-150 relative focus-ring ${
          isActive
            ? 'bg-accent-amber/10 text-accent-amber border border-accent-amber/25 shadow-[inset_0_0_0_1px_rgba(255,176,32,0.08)]'
            : 'text-tertiary hover:text-secondary hover:bg-panel/60 border border-transparent'
        }`
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-5 bg-accent-amber rounded-full shadow-[0_0_6px_rgba(255,176,32,0.5)]" />
          )}
          <item.icon className="w-3.5 h-3.5 shrink-0" strokeWidth={1.5} />
          <div className="flex flex-col min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="truncate">{item.label}</span>
              {badge != null && badge > 0 && (
                <span className="inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full text-[9px] font-bold leading-none bg-gov-red-muted text-gov-red border border-gov-red/25">
                  {badge}
                </span>
              )}
            </div>
            <span className="text-[9px] text-tertiary/60 truncate">{item.desc}</span>
          </div>
        </>
      )}
    </NavLink>
  )
})

// ── Consolidated terminal status dock ─────────────────────
const StatusDock = memo(function StatusDock() {
  const health = useEngineHealth()
  const engine = useSystemSnapshot(systemSelectors.engineStatus).data

  const engineAlive = health.data?.engine_alive ?? false
  const isRunning = !health.isError && !!engineAlive && !engine?.market_closed
  const running = engineAlive && !health.isError
  const label = health.isError ? 'OFFLINE' : health.isLoading ? '…' : engine?.market_closed ? 'CLOSED' : 'RUNNING'
  const dot = isRunning ? 'bg-gov-green' : 'bg-gov-red'
  const textColor = running && !engine?.market_closed ? 'text-gov-green' : 'text-gov-red'
  const marketClosed = engine?.market_closed
  const lastUpdate = engine?.last_update
  const dotClass = isRunning ? 'bg-gov-green' : 'bg-gov-red'

  return (
    <div className="shrink-0 border-t border-default px-3 py-2.5 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 text-[10px] font-mono tracking-tight">
          <span className={`inline-flex w-1.5 h-1.5 rounded-full ${dotClass} ${running ? '' : 'animate-pulse'}`} />
          <span className={`font-semibold ${textColor}`}>ENGINE · {label}</span>
        </span>
        <span className={`inline-flex items-center gap-1.5 text-[10px] font-mono ${marketClosed ? 'text-gov-yellow' : 'text-gov-green'}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${marketClosed ? 'bg-gov-yellow' : 'bg-gov-green'}`} />
          {marketClosed ? 'Closed' : 'Open'}
        </span>
      </div>
      <div className="flex items-center justify-between gap-2 text-[9px] font-mono text-tertiary/70">
        <span>EXC · 9879</span>
        <span>{lastUpdate ? `${formatTimeAgo(lastUpdate)} ago` : 'no snapshot'}</span>
      </div>
    </div>
  )
})

function Sidebar({ open, onClose }: SidebarProps) {
  const badges = useSidebarBadges()
  const { open: openPalette } = useCommandPalette()
  const asideRef = useRef<HTMLElement>(null)

  // Mobile drawer: focus trap + restore + background scroll lock (only while open).
  useEffect(() => {
    if (!open) return
    const el = asideRef.current
    if (!el) return
    const previouslyFocused = document.activeElement as HTMLElement | null

    const focusables = () => Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE))
    focusables()[0]?.focus()

    const handleKey = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return
      const nodes = focusables()
      if (nodes.length === 0) return
      const first = nodes[0]
      const last = nodes[nodes.length - 1]
      if (e.shiftKey) {
        if (document.activeElement === first) { e.preventDefault(); last.focus() }
      } else if (document.activeElement === last) {
        e.preventDefault(); first.focus()
      }
    }

    document.addEventListener('keydown', handleKey)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', handleKey)
      document.body.style.overflow = prevOverflow
      previouslyFocused?.focus()
    }
  }, [open])

  const handleKeyDown = useCallback((e: React.KeyboardEvent, currentId: string) => {
    const currentIndex = SIDEBAR_NAV_ITEMS.findIndex(item => item.id === currentId)
    if (currentIndex === -1) return

    switch (e.key) {
      case 'ArrowDown': {
        e.preventDefault()
        const next = SIDEBAR_NAV_ITEMS[(currentIndex + 1) % SIDEBAR_NAV_ITEMS.length]
        document.getElementById(`nav-${next.id}`)?.focus()
        break
      }
      case 'ArrowUp': {
        e.preventDefault()
        const prev = SIDEBAR_NAV_ITEMS[(currentIndex - 1 + SIDEBAR_NAV_ITEMS.length) % SIDEBAR_NAV_ITEMS.length]
        document.getElementById(`nav-${prev.id}`)?.focus()
        break
      }
      case 'Home': {
        e.preventDefault()
        document.getElementById(`nav-${SIDEBAR_NAV_ITEMS[0].id}`)?.focus()
        break
      }
      case 'End': {
        e.preventDefault()
        document.getElementById(`nav-${SIDEBAR_NAV_ITEMS[SIDEBAR_NAV_ITEMS.length - 1].id}`)?.focus()
        break
      }
      case 'Escape': {
        onClose()
        break
      }
    }
  }, [onClose])

  return (
    <>
      {open && (
        <div
          className="fixed inset-0 bg-black/60 z-40 lg:hidden backdrop-blur-sm"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        ref={asideRef}
        role={open ? 'dialog' : undefined}
        aria-modal={open ? 'true' : undefined}
        aria-label="Navigation"
        className={`
          fixed inset-y-0 left-0 z-50 w-[232px] bg-surface border-r border-default
          shadow-[inset_-1px_0_0_rgba(255,255,255,0.02)]
          transform transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]
          lg:relative lg:inset-auto lg:z-auto lg:translate-x-0 lg:sticky lg:top-[var(--header-height)] lg:h-[calc(100vh-var(--header-height))] lg:overflow-y-auto
          flex flex-col
          ${open ? 'translate-x-0' : '-translate-x-full'}
        `}
      >
        {/* Region 1: Brand + Search sheet */}
        <div className="shrink-0 px-3 pt-2.5 pb-2 border-b border-default space-y-2">
          <div className="flex items-center gap-2">
            <div className="w-5 h-5 rounded-md bg-accent-amber flex items-center justify-center shrink-0">
              <TrendingUp className="w-2.5 h-2.5 text-[#0a0602]" strokeWidth={2.25} />
            </div>
            <span className="text-xs font-bold tracking-tight text-primary truncate">Quorrin</span>
            <button
              type="button"
              onClick={onClose}
              className="lg:hidden ml-auto min-h-[36px] min-w-[36px] flex items-center justify-center rounded-md hover:bg-panel transition-colors focus-ring shrink-0 active:scale-95"
              aria-label="Close navigation"
            >
              <X className="w-3.5 h-3.5 text-tertiary" strokeWidth={2} />
            </button>
          </div>
          <button
            type="button"
            onClick={openPalette}
            className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md border border-default bg-panel/40 text-tertiary hover:border-strong hover:text-secondary transition-colors focus-ring active:scale-[0.99]"
            aria-label="Search pages, assets, and sections"
          >
            <Search className="w-3 h-3 shrink-0" strokeWidth={2} />
            <span className="text-[10px] font-medium truncate">Search…</span>
            <span className="ml-auto inline-flex items-center gap-0.5 text-[9px] font-mono text-tertiary/60 shrink-0">
              <Command className="w-2.5 h-2.5" strokeWidth={2} />K
            </span>
          </button>
        </div>

        {/* Region 2: Navigation */}
        <nav
          aria-label="Dashboard sections"
          className="flex-1 overflow-y-auto py-3 px-2 space-y-1 scrollbar-thin"
        >
          {NAV_GROUPS.map((group, gi) => (
            <div key={group.title}>
              <p className="flex items-center gap-1.5 text-[10px] font-semibold text-tertiary uppercase tracking-wider px-2 py-1.5">
                <group.icon className="w-3 h-3 opacity-50" strokeWidth={1.5} />
                {group.title}
              </p>
              <div className="space-y-0.5 ml-1">
                {group.items.map(item => (
                  <NavItem key={item.id} item={item} badge={item.badgeKey ? badges[item.badgeKey] : undefined} onClose={onClose} onKeyDown={handleKeyDown} />
                ))}
              </div>
              {gi < NAV_GROUPS.length - 1 && <Divider className="my-1.5 mx-2" />}
            </div>
          ))}
        </nav>

        {/* Region 3: Terminal status dock */}
        <StatusDock />
      </aside>
    </>
  )
}

export default memo(Sidebar)