import { useState, useCallback, type ReactNode } from 'react'
import { useSystemSnapshot } from '../../hooks/useSystemSnapshot'
import { useSnapshotReconciler } from '../../hooks/useSnapshotReconciler'
import { useSystemIntegrity } from '../../hooks/useSystemIntegrity'
import { SystemDegradedBanner } from '../ui/SystemDegradedBanner'
import LoadingScreen from '../ui/LoadingScreen'
import ErrorScreen from '../ui/ErrorScreen'
import Header from '../Header'
import TabBar from './TabBar'
import Sidebar from './Sidebar'
import TickerRail from './TickerRail'
import EmergencyHaltBanner from '../EmergencyHaltBanner'

interface AppShellProps {
  children: ReactNode
}

export default function AppShell({ children }: AppShellProps) {
  const { data: bundle } = useSystemSnapshot()
  useSnapshotReconciler(bundle)
  const integrity = useSystemIntegrity(bundle)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const toggleSidebar = useCallback(() => setSidebarOpen(prev => !prev), [])
  const closeSidebar = useCallback(() => setSidebarOpen(false), [])

  if (integrity.shouldBlockRender) {
    return (
      <>
        {!integrity.isBroken && <Header onMenuClick={toggleSidebar} />}
        <ErrorScreen
          title="Engine unavailable"
          message="Couldn't load the engine snapshot. It may be restarting."
        />
      </>
    )
  }

  return (
    <div className="min-h-screen bg-app text-secondary flex flex-col">
      <TickerRail />
      <Header onMenuClick={toggleSidebar} />
      <SystemDegradedBanner integrity={integrity} />
      <EmergencyHaltBanner />

      <div className="flex-1 flex relative max-w-[90rem] mx-auto w-full">
        <Sidebar open={sidebarOpen} onClose={closeSidebar} />

        <div className="flex-1 flex flex-col min-w-0">
          <div className="shrink-0 border-b border-default">
            <TabBar />
          </div>

          <main className="flex-1 min-w-0 px-4 sm:px-7 py-5 sm:py-7 animate-fade-in">
            {children}
          </main>
        </div>
      </div>
    </div>
  )
}
