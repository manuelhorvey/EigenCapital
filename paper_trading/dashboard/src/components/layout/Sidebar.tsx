import { useCallback, useRef } from 'react'
import { useActiveSection } from '../../hooks/useActiveSection'
import {
  LayoutDashboard,
  TrendingUp,
  Zap,
  BarChart3,
  Activity,
  Heart,
  type LucideIcon,
} from 'lucide-react'

interface NavItem {
  id: string
  label: string
  icon: LucideIcon
}

interface NavGroup {
  title: string
  items: NavItem[]
}

const NAV_GROUPS: NavGroup[] = [
  {
    title: 'Monitor',
    items: [{ id: 'monitor', label: 'System Monitor', icon: LayoutDashboard }],
  },
  {
    title: 'Portfolio',
    items: [{ id: 'portfolio', label: 'Portfolio', icon: TrendingUp }],
  },
  {
    title: 'Signals & Execution',
    items: [
      { id: 'signals', label: 'Signals', icon: Zap },
      { id: 'execution', label: 'Execution', icon: BarChart3 },
    ],
  },
  {
    title: 'Trades',
    items: [{ id: 'trades', label: 'Trades', icon: Activity }],
  },
  {
    title: 'Governance',
    items: [{ id: 'risk', label: 'System Health', icon: Heart }],
  },
]

const allItems = NAV_GROUPS.flatMap(g => g.items)

interface SidebarProps {
  open: boolean
  onClose: () => void
}

export default function Sidebar({ open, onClose }: SidebarProps) {
  const active = useActiveSection()
  const navRef = useRef<HTMLElement>(null)

  const scrollTo = useCallback((id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
    onClose()
  }, [onClose])

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
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        role={open ? 'dialog' : undefined}
        aria-modal={open ? 'true' : undefined}
        aria-label="Navigation"
        className={`
          fixed inset-y-0 left-0 z-50 w-[220px] bg-app border-r border-default
          transform transition-transform duration-300 ease-[cubic-bezier(0.4,0,0.2,1)]
          lg:relative lg:inset-auto lg:z-auto lg:translate-x-0 lg:sticky lg:top-[45px] lg:h-[calc(100vh-45px)] lg:overflow-y-auto
          ${open ? 'translate-x-0' : '-translate-x-full'}
        `}
      >
        <nav
          ref={navRef}
          role="tree"
          aria-label="Dashboard sections"
          className="py-4 px-3 space-y-5"
        >
          {NAV_GROUPS.map(group => (
            <div key={group.title} role="treegroup" aria-label={group.title}>
              <p className="text-[10px] font-semibold text-tertiary uppercase tracking-widest px-2 mb-1.5">
                {group.title}
              </p>
              <div className="space-y-0.5">
                {group.items.map(item => {
                  const isActive = active === item.id
                  return (
                    <button
                      key={item.id}
                      id={`nav-${item.id}`}
                      role="treeitem"
                      aria-current={isActive ? 'page' : undefined}
                      tabIndex={isActive ? 0 : -1}
                      onClick={() => scrollTo(item.id)}
                      onKeyDown={e => handleKeyDown(e, item.id)}
                      className={`
                        w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-xs font-medium
                        transition-all duration-150 relative
                        ${isActive
                          ? 'bg-accent-emerald/10 text-accent-emerald border border-accent-emerald/20'
                          : 'text-tertiary hover:text-secondary hover:bg-panel border border-transparent'
                        }
                      `}
                    >
                      {isActive && (
                        <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 bg-accent-emerald rounded-full" />
                      )}
                      <item.icon className="w-3.5 h-3.5 shrink-0" strokeWidth={1.5} />
                      {item.label}
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </nav>
      </aside>
    </>
  )
}
