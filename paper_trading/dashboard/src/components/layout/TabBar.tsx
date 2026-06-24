import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Zap, BarChart3, Heart } from 'lucide-react'

interface TabItem {
  to: string
  label: string
  icon: React.ReactNode
  badge?: string
}

const TABS: TabItem[] = [
  { to: '/dashboard', label: 'Dashboard', icon: <LayoutDashboard className="w-3.5 h-3.5" strokeWidth={1.5} /> },
  { to: '/trading', label: 'Trading', icon: <Zap className="w-3.5 h-3.5" strokeWidth={1.5} /> },
  { to: '/execution', label: 'Execution', icon: <BarChart3 className="w-3.5 h-3.5" strokeWidth={1.5} /> },
  { to: '/risk', label: 'Risk', icon: <Heart className="w-3.5 h-3.5" strokeWidth={1.5} /> },
]

export default function TabBar() {
  return (
    <nav className="flex items-center gap-1 px-4" aria-label="Main tabs">
      {TABS.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end
          className={({ isActive }) =>
            `flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              isActive
                ? 'bg-accent-emerald/8 text-accent-emerald border border-accent-emerald/20'
                : 'text-tertiary hover:text-secondary hover:bg-panel/60 border border-transparent'
            }`
          }
        >
          {tab.icon}
          {tab.label}
          {tab.badge && (
            <span className="text-[9px] px-1 py-0.5 rounded bg-panel text-tertiary">{tab.badge}</span>
          )}
        </NavLink>
      ))}
    </nav>
  )
}
