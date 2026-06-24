import { memo, useCallback } from 'react'
import { NavLink } from 'react-router-dom'
import { X, TrendingUp, LayoutDashboard, Zap, BarChart3, Heart } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useEngineHealth } from '../../hooks/useEngineHealth'
import Divider from '../ui/Divider'

type TabId = 'dashboard' | 'trading' | 'execution' | 'risk'

interface NavItemDef {
  id: TabId
  to: string
  label: string
  icon: LucideIcon
  desc: string
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
      { id: 'dashboard', to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard, desc: 'Health + alerts + portfolio summary' },
    ],
  },
  {
    title: 'Trading',
    icon: TrendingUp,
    items: [
      { id: 'trading', to: '/trading', label: 'Trading', icon: Zap, desc: 'Signals, fills, open trades' },
      { id: 'execution', to: '/execution', label: 'Execution', icon: BarChart3, desc: 'Slippage, quality, attribution' },
    ],
  },
  {
    title: 'Analysis',
    icon: Heart,
    items: [
      { id: 'risk', to: '/risk', label: 'Risk', icon: Heart, desc: 'Health scores, governance, constraints' },
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
  onClose: () => void
  onKeyDown: (e: React.KeyboardEvent, id: string) => void
}

const EngineBadge = memo(function EngineBadge() {
  const health = useEngineHealth()
  const engineAlive = health.data?.engine_alive ?? false
  const label = health.isError ? 'OFF' : health.isLoading ? '...' : engineAlive ? 'RUNNING' : 'OFF'
  const isRunning = !health.isError && engineAlive

  return (
    <div className="flex items-center gap-1.5 min-w-0">
      <span className={`inline-block w-1.5 h-1.5 rounded-full ${isRunning ? 'bg-gov-green' : 'bg-gov-red'} ${isRunning ? '' : 'animate-pulse'}`} />
      <span className={`text-[10px] font-semibold font-mono tracking-tight ${isRunning ? 'text-gov-green' : 'text-gov-red'}`}>
        {label}
      </span>
    </div>
  )
})

const NavItem = memo(function NavItem({ item, onClose, onKeyDown }: NavItemProps) {
  return (
    <NavLink
      id={`nav-${item.id}`}
      to={item.to}
      end
      role="treeitem"
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
          <div className="flex flex-col min-w-0">
            <span className="truncate">{item.label}</span>
            <span className="text-[9px] text-tertiary/60 truncate">{item.desc}</span>
          </div>
        </>
      )}
    </NavLink>
  )
})

function Sidebar({ open, onClose }: SidebarProps) {
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
        {/* Region 1: Engine status strip (light dynamic — useEngineHealth only) */}
        <div className="shrink-0 flex items-center justify-between gap-2 px-3 py-2.5 border-b border-default">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-6 h-6 rounded-md bg-accent-emerald/85 flex items-center justify-center shrink-0">
              <TrendingUp className="w-3 h-3 text-[#08090c]" strokeWidth={2.25} />
            </div>
            <EngineBadge />
          </div>
          <button
            type="button"
            onClick={onClose}
            className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-md hover:bg-panel transition-colors lg:hidden focus-ring shrink-0 active:scale-95"
            aria-label="Close navigation"
          >
            <X className="w-3.5 h-3.5 text-tertiary" strokeWidth={2} />
          </button>
        </div>

        {/* Region 2: Navigation shell (static — no data dependencies) */}
        <nav
          role="tree"
          aria-label="Dashboard sections"
          className="flex-1 overflow-y-auto py-3 px-2 space-y-1 scrollbar-thin"
        >
          {NAV_GROUPS.map((group, gi) => (
            <div key={group.title} role="treegroup" aria-label={group.title}>
              <p className="flex items-center gap-1.5 text-[10px] font-semibold text-tertiary uppercase tracking-wider px-2 py-1.5">
                <group.icon className="w-3 h-3 opacity-50" strokeWidth={1.5} />
                {group.title}
              </p>
              <div className="space-y-0.5 ml-1">
                {group.items.map(item => (
                  <NavItem key={item.id} item={item} onClose={onClose} onKeyDown={handleKeyDown} />
                ))}
              </div>
              {gi < NAV_GROUPS.length - 1 && <Divider className="my-1.5 mx-2" />}
            </div>
          ))}
        </nav>
      </aside>
    </>
  )
}

export default memo(Sidebar)
