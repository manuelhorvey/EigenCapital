import { useState, useCallback, type ReactNode } from 'react'
import { useSystemSnapshot } from '../../hooks/useSystemSnapshot'
import { useSnapshotReconciler } from '../../hooks/useSnapshotReconciler'
import { useSystemIntegrity } from '../../hooks/useSystemIntegrity'
import { SystemDegradedBanner } from '../ui/SystemDegradedBanner'
import ErrorScreen from '../ui/ErrorScreen'
import TabBar from './TabBar'
import Sidebar from './Sidebar'
import TickerRail from './TickerRail'
import EmergencyHaltBanner from '../EmergencyHaltBanner'

interface AppShellProps {
  children: ReactNode
}

/** Root layout wrapping all pages. Renders ticker rail, sidebar, tab bar, and content. @param {{ children: ReactNode }} props */
export default function AppShell({ children }: AppShellProps) {
  const mainId = 'main-content'
  const { data: bundle } = useSystemSnapshot()
  useSnapshotReconciler(bundle)
  const integrity = useSystemIntegrity(bundle)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const toggleSidebar = useCallback(() => setSidebarOpen(prev => !prev), [])
  const closeSidebar = useCallback(() => setSidebarOpen(false), [])

  if (integrity.shouldBlockRender) {
    return (
      <>
        <ErrorScreen
          title="Engine unavailable"
          message="Couldn't load the engine snapshot. It may be restarting."
        />
      </>
    )
  }

  return (
    <div className="min-h-screen bg-app text-secondary flex flex-col">
      <TickerRail onToggleSidebar={toggleSidebar} />
      <SystemDegradedBanner integrity={integrity} />
      <EmergencyHaltBanner />

      <div className="flex-1 flex relative max-w-[90rem] mx-auto w-full">
        <Sidebar open={sidebarOpen} onClose={closeSidebar} />

        <div className="flex-1 flex flex-col min-w-0">
          <div className="shrink-0 border-b border-default">
            <TabBar />
          </div>

          {/* Skip-to-content link — visible only when focused via keyboard (WCAG 2.4.1). */}
          <a
            href={`#${mainId}`}
            className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:px-3 focus:py-2 focus:rounded-md focus:bg-panel focus:border focus:border-strong focus:text-primary focus:text-xs focus:font-medium focus:shadow-card"
          >
            Skip to main content
          </a>
          <main id={mainId} className="flex-1 min-w-0 px-4 sm:px-7 py-5 sm:py-7 animate-fade-in" role="main" aria-label="Dashboard content">
            {children}
          </main>
        </div>
      </div>
    </div>
  )
}
