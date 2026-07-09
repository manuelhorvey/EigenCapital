import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Zap, BarChart3, Shield } from 'lucide-react'
import { useSidebarBadges } from '../../hooks/useSidebarBadges'

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

/** Tab navigation bar — shown on mobile (< lg) below the TopBar.
 *  On desktop (lg+) the TopBar includes nav tabs and the collapsible
 *  sidebar provides navigation context, so this is hidden. */
export default function TabBar() {
  const badges = useSidebarBadges()

  return (
    <nav
      className="lg:hidden flex items-center gap-0.5 px-2 overflow-x-auto scrollbar-none border-b border-default shrink-0"
      aria-label="Main tabs"
    >
      {TABS.map((tab) => {
        const badge = tab.badgeKey ? badges[tab.badgeKey] : undefined
        return (
          <NavLink
            key={tab.to}
            to={tab.to}
            end
            aria-label={tab.label}
            className={({ isActive }) =>
              `flex items-center gap-1 px-2 py-2 text-xs font-medium rounded-md transition-colors shrink-0 ${
                isActive
                  ? 'bg-accent-emerald/8 text-accent-emerald border border-accent-emerald/20'
                  : 'text-tertiary hover:text-secondary hover:bg-panel/60 border border-transparent'
              } active:scale-95`
            }
          >
            {tab.icon}
            <span className="ml-0.5">{tab.label}</span>
            {badge != null && badge > 0 && (
              <span className="inline-flex items-center justify-center min-w-[14px] h-3.5 px-1 rounded-full text-[8px] font-bold leading-none bg-gov-red-muted text-gov-red border border-gov-red/25">
                {badge}
              </span>
            )}
          </NavLink>
        )
      })}
    </nav>
  )
}
