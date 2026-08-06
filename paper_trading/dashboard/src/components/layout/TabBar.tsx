import { NavLink } from 'react-router-dom'
import { useSidebarBadges } from '../../hooks/useSidebarBadges'
import { NAV_ITEMS } from '../../lib/navigation'

export default function TabBar() {
  const badges = useSidebarBadges()

  return (
    <nav className="flex items-center gap-1 px-2 sm:px-4 overflow-x-auto scrollbar-none" aria-label="Main tabs">
      {NAV_ITEMS.map((tab) => {
        const badge = tab.badgeKey ? badges[tab.badgeKey] : undefined
        const Icon = tab.icon
        return (
          <NavLink
            key={tab.to}
            to={tab.to}
            end
            aria-label={tab.label}
            className={({ isActive }) =>
              `flex items-center gap-1.5 px-2 sm:px-3 py-2 sm:py-1.5 text-2xs sm:text-xs font-medium rounded-md transition-colors shrink-0 ${
                isActive
                  ? 'bg-accent-amber/10 text-accent-amber border border-accent-amber/25'
                  : 'text-tertiary hover:text-secondary hover:bg-panel/60 border border-transparent'
              } active:scale-95 sm:active:scale-100`
            }
          >
            <Icon className="w-3.5 h-3.5" strokeWidth={1.5} />
            <span className="hidden sm:inline">{tab.label}</span>
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