import { type ReactNode, useCallback } from 'react'

export interface TabDef<T extends string = string> {
  id: T
  label: string
  icon?: ReactNode
}

interface TabsProps<T extends string = string> {
  tabs: TabDef<T>[]
  activeTab: T
  onTabChange: (id: T) => void
  className?: string
  size?: 'sm' | 'md'
}

const sizeStyles = {
  sm: 'text-2xs px-2 py-1.5 gap-1',
  md: 'text-xs px-3 py-2 gap-1.5',
}

/**
 * Unified tab bar component — replaces duplicated tab UIs across the dashboard.
 * Generic over tab ID type T for type-safe tab identifiers.
 *
 * Use TabPanel for each tab's content to maintain proper ARIA relationships.
 *
 * Usage:
 *   const [tab, setTab] = useState('overview')
 *   <Tabs tabs={TABS} activeTab={tab} onTabChange={setTab} />
 *   <TabPanel id="overview" active={tab === 'overview'}>...</TabPanel>
 *
 * @param tabs - Array of { id, label, icon? }
 * @param activeTab - Currently active tab id
 * @param onTabChange - Callback when user clicks a tab
 * @param size - 'sm' for compact, 'md' for normal
 */
export default function Tabs<T extends string>({
  tabs,
  activeTab,
  onTabChange,
  className = '',
  size = 'md',
}: TabsProps<T>) {
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const currentIdx = tabs.findIndex(t => t.id === activeTab)
      if (currentIdx === -1) return

      let nextIdx: number | null = null
      switch (e.key) {
        case 'ArrowRight':
          nextIdx = (currentIdx + 1) % tabs.length
          break
        case 'ArrowLeft':
          nextIdx = (currentIdx - 1 + tabs.length) % tabs.length
          break
        case 'Home':
          nextIdx = 0
          break
        case 'End':
          nextIdx = tabs.length - 1
          break
      }
      if (nextIdx !== null) {
        e.preventDefault()
        onTabChange(tabs[nextIdx].id)
      }
    },
    [tabs, activeTab, onTabChange],
  )

  return (
    <div
      className={`flex items-center gap-0 border-b border-default shrink-0 overflow-x-auto ${className}`}
      role="tablist"
      aria-label="Tab navigation"
      onKeyDown={handleKeyDown}
    >
      {tabs.map(t => {
        const isActive = activeTab === t.id
        return (
          <button
            key={t.id}
            id={`ec-tab-${t.id}`}
            role="tab"
            aria-selected={isActive}
            aria-controls={`ec-tab-panel-${t.id}`}
            tabIndex={isActive ? 0 : -1}
            onClick={() => onTabChange(t.id)}
            className={`flex items-center ${sizeStyles[size]} font-medium border-b-2 transition-all shrink-0 focus-ring ${
              isActive
                ? 'text-accent-emerald border-accent-emerald'
                : 'text-tertiary border-transparent hover:text-secondary hover:border-default/40'
            }`}
          >
            {t.icon && <span className="shrink-0">{t.icon}</span>}
            {t.label}
          </button>
        )
      })}
    </div>
  )
}

interface TabPanelProps {
  id: string
  active: boolean
  children: ReactNode
  className?: string
}

/**
 * Tab panel wrapper — provides ARIA attributes for the active tab panel.
 * Must be used with Tabs component for proper accessibility.
 *
 * Usage:
 *   <TabPanel id="overview" active={tab === 'overview'}>
 *     <OverviewContent />
 *   </TabPanel>
 */
export function TabPanel({ id, active, children, className = '' }: TabPanelProps) {
  if (!active) return null
  return (
    <div
      id={`ec-tab-panel-${id}`}
      role="tabpanel"
      aria-labelledby={`ec-tab-${id}`}
      tabIndex={0}
      className={`flex-1 overflow-y-auto outline-none ${className}`}
    >
      {children}
    </div>
  )
}
