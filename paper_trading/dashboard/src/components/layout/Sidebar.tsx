import { memo, useCallback } from 'react'
import { NavLink } from 'react-router-dom'
import { X, TrendingUp, LayoutDashboard, Zap, BarChart3, Shield } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useSidebarBadges, type EngineState } from '../../hooks/useSidebarBadges'
import Divider from '../ui/Divider'

type TabId = 'dashboard' | 'engine' | 'trading' | 'execution' | 'risk'

interface NavItemDef {
  id: TabId
  to: string
  label: string
  icon: LucideIcon
  desc: string
  badgeKey?: 'trading' | 'risk'
}

interface NavGroupDef {
  title: string
  icon: LucideIcon
  items: NavItemDef[]
}

const NAV_GROUPS: NavGroupDef[] = [
  {
    title: 'Overview',
    icon: LayoutDashboard,
    items: [
      { id: 'dashboard', to: '/', label: 'Dashboard', icon: LayoutDashboard, desc: 'Status, equity, positions' },
    ],
  },
  {
    title: 'Trading',
    icon: TrendingUp,
    items: [
      { id: 'trading', to: '/trading', label: 'Trading', icon: Zap, desc: 'Signals, fills, open trades', badgeKey: 'trading' },
      { id: 'execution', to: '/execution', label: 'Execution', icon: BarChart3, desc: 'Slippage, quality, attribution' },
    ],
  },
  {
    title: 'Risk',
    icon: Shield,
    items: [
      { id: 'risk', to: '/risk', label: 'Risk', icon: Shield, desc: 'Health scores, governance, constraints', badgeKey: 'risk' },
    ],
  },
]

const allItems = NAV_GROUPS.flatMap(g => g.items)

interface SidebarProps {
  open: boolean
  onClose: () => void
}

interface NavItemProps {
  item: NavItemDef
  badge?: number
  /** Engine heartbeat dot rendered inline on the Dashboard nav item. */
  engine?: EngineState
  onClose: () => void
  onKeyDown: (e: React.KeyboardEvent, id: string) => void
}

function engineDotClass(state: EngineState | undefined): string | null {
  if (state === 'alive') return 'bg-gov-green'
  if (state === 'stale') return 'bg-gov-yellow'
  if (state === 'dead') return 'bg-gov-red'
  return null
}

const NavItem = memo(function NavItem({ item, badge, engine, onClose, onKeyDown }: NavItemProps) {
  const dot = engineDotClass(engine)
  return (
    <NavLink
      id={`nav-${item.id}`}
      to={item.to}
      end
      role="listitem"
      onClick={onClose}
      onKeyDown={e => onKeyDown(e, item.id)}
      className={({ isActive }) =>
        `w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-xs font-medium
        transition-all duration-150 relative focus-ring ${
          isActive
            ? 'bg-accent-emerald/8 text-accent-emerald border border-accent-emerald/20 shadow-[inset_0_0_0_1px_rgba(20,184,166,0.08)]'
            : 'text-tertiary hover:text-secondary hover:bg-panel/60 border border-transparent'
        }`
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-4 bg-accent-emerald rounded-full shadow-[0_0_4px_rgba(20,184,166,0.4)]" />
          )}
          <item.icon className="w-3.5 h-3.5 shrink-0" strokeWidth={1.5} />
          <div className="flex flex-col min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className="truncate">{item.label}</span>
              {dot && (
                <span
                  className={`w-1.5 h-1.5 rounded-full shrink-0 ${dot}`}
                  aria-label={`Engine ${engine}`}
                  title={`Engine ${engine}`}
                />
              )}
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

function Sidebar({ open, onClose }: SidebarProps) {
  const badges = useSidebarBadges()
  const handleKeyDown = useCallback((e: React.KeyboardEvent, currentId: string) => {
    const currentIndex = allItems.findIndex(item => item.id === currentId)
    if (currentIndex === -1) return

    switch (e.key) {
      case 'ArrowDown': {
        e.preventDefault()
        const next = allItems[(currentIndex + 1) % allItems.length]
        document.getElementById(`nav-${next.id}`)?.focus()
        break
      }
      case 'ArrowUp': {
        e.preventDefault()
        const prev = allItems[(currentIndex - 1 + allItems.length) % allItems.length]
        document.getElementById(`nav-${prev.id}`)?.focus()
        break
      }
      case 'Home': {
        e.preventDefault()
        document.getElementById(`nav-${allItems[0].id}`)?.focus()
        break
      }
      case 'End': {
        e.preventDefault()
        document.getElementById(`nav-${allItems[allItems.length - 1].id}`)?.focus()
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
        role={open ? 'dialog' : undefined}
        aria-modal={open ? 'true' : undefined}
        aria-label="Navigation"
        className={`
          fixed inset-y-0 left-0 z-50 w-[220px] bg-surface border-r border-default
          shadow-[inset_-1px_0_0_rgba(255,255,255,0.02)]
          transform transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]
          lg:relative lg:inset-auto lg:z-auto lg:translate-x-0 lg:sticky lg:top-[45px] lg:h-[calc(100vh-45px)] lg:overflow-y-auto
          flex flex-col
          ${open ? 'translate-x-0' : '-translate-x-full'}
        `}
      >
        {/* Close button — mobile only, lives at the top of the rail. */}
        <div className="shrink-0 flex items-center justify-end px-2 py-1.5 border-b border-default lg:hidden">
          <button
            type="button"
            onClick={onClose}
            className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-md hover:bg-panel transition-colors focus-ring shrink-0 active:scale-95"
            aria-label="Close navigation"
          >
            <X className="w-3.5 h-3.5 text-tertiary" strokeWidth={2} />
          </button>
        </div>

        {/* Navigation shell — flat nav with roving tabindex (ArrowUp/Down, Home/End, Escape). */}
        <nav
          role="list"
          aria-label="Dashboard sections"
          className="flex-1 overflow-y-auto py-3 px-2 space-y-1 scrollbar-thin"
        >
          {NAV_GROUPS.map((group, gi) => (
            <div key={group.title} aria-label={group.title}>
              <p className="flex items-center gap-1.5 text-[10px] font-semibold text-tertiary uppercase tracking-wider px-2 py-1.5">
                <group.icon className="w-3 h-3 opacity-50" strokeWidth={1.5} />
                {group.title}
              </p>
              <div className="space-y-0.5 ml-1">
                {group.items.map(item => (
                  <NavItem
                    key={item.id}
                    item={item}
                    badge={item.badgeKey ? badges[item.badgeKey] : undefined}
                    engine={item.id === 'dashboard' ? badges.engine : undefined}
                    onClose={onClose}
                    onKeyDown={handleKeyDown}
                  />
                ))}
              </div>
              {gi < NAV_GROUPS.length - 1 && <Divider className="my-1.5 mx-2" />}
            </div>
          ))}

          {/* Inline-pinned engine badge below the nav for at-a-glance status
              without requiring the operator to focus the nav item — IA-1
              adds an engine-state dot on the Dashboard nav item; this strip
              gives the same state in tabular form for sighted scanning. */}
          <div className="mt-3 px-2 pt-2 border-t border-default text-2xs font-mono tabular-nums text-tertiary flex items-center gap-1.5">
            <span
              className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                engineDotClass(badges.engine) ?? 'bg-gov-init/50'
              }`}
              aria-label={`Engine ${badges.engine ?? 'unknown'}`}
            />
            <span className="uppercase tracking-wider">engine</span>
            <span className="ml-auto text-secondary">{badges.engine ?? 'loading…'}</span>
          </div>
        </nav>
      </aside>
    </>
  )
}

/**
 * Navigation sidebar with grouped nav items, engine heartbeat dot, and badge counts.
 * Renders as an off-canvas overlay on mobile and a persistent sidebar on desktop.
 * @param {{ open: boolean, onClose: () => void }} props
 */
export default memo(Sidebar)
