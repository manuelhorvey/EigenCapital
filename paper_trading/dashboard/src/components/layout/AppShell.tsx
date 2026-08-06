import { useState, useCallback, useEffect, type ReactNode } from 'react'
import { useSystemSnapshot } from '../../hooks/useSystemSnapshot'
import { useSnapshotReconciler } from '../../hooks/useSnapshotReconciler'
import { useSystemIntegrity } from '../../hooks/useSystemIntegrity'
import { SystemDegradedBanner } from '../ui/SystemDegradedBanner'
import LoadingScreen from '../ui/LoadingScreen'
import ErrorScreen from '../ui/ErrorScreen'
import Header from '../Header'
import TabBar from './TabBar'
import Sidebar from './Sidebar'
import EmergencyHaltBanner from '../EmergencyHaltBanner'

interface AppShellProps {
  children: ReactNode
}

// If the engine snapshot has not arrived within this window at cold start,
// surface the offline ErrorScreen (with retry) instead of an infinite spinner.
const CONNECTION_TIMEOUT_MS = 12_000

export default function AppShell({ children }: AppShellProps) {
  const { data: bundle, isPending } = useSystemSnapshot()
  useSnapshotReconciler(bundle)
  const integrity = useSystemIntegrity(bundle)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const toggleSidebar = useCallback(() => setSidebarOpen(prev => !prev), [])
  const closeSidebar = useCallback(() => setSidebarOpen(false), [])
  const [connectionTimedOut, setConnectionTimedOut] = useState(false)

  // Track whether we are still waiting for the *first* snapshot and arm the
  // timeout only while that is true (reset when a snapshot eventually arrives).
  useEffect(() => {
    if (bundle || !isPending) {
      setConnectionTimedOut(false)
      return
    }
    const t = setTimeout(() => setConnectionTimedOut(true), CONNECTION_TIMEOUT_MS)
    return () => clearTimeout(t)
  }, [bundle, isPending])

  if (integrity.shouldBlockRender) {
    if (!bundle || isPending) {
      if (connectionTimedOut) {
        return (
          <ErrorScreen
            title="Engine Not Reachable"
            message="The paper trading engine did not respond on port 5000. Make sure it is running, then retry."
            onRetry={() => window.location.reload()}
          />
        )
      }
      return <LoadingScreen title="Loading system snapshot" subtitle="Connecting to the paper trading engine…" />
    }
    return (
      <>
        {!integrity.isBroken && <Header onMenuClick={toggleSidebar} />}
        <ErrorScreen
          title="System Unavailable"
          message="The engine snapshot could not be loaded. The system may be restarting."
        />
      </>
    )
  }

  return (
    <div className="min-h-screen bg-app text-secondary flex flex-col">
      {/* Skip link for keyboard / screen-reader users.
          Uses a button + programmatic focus (not href="#") so it doesn't
          conflict with the HashRouter's hash-based navigation. */}
      <button
        type="button"
        onClick={() => {
          const main = document.getElementById('main-content')
          main?.focus()
          main?.scrollIntoView()
        }}
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:px-3 focus:py-2 focus:rounded-md focus:bg-accent-amber focus:text-[#0a0602] focus:text-xs focus:font-semibold"
      >
        Skip to main content
      </button>

      <Header onMenuClick={toggleSidebar} />
      <SystemDegradedBanner integrity={integrity} />
      <EmergencyHaltBanner />

      <div className="flex-1 flex relative max-w-[90rem] mx-auto w-full">
        <Sidebar open={sidebarOpen} onClose={closeSidebar} />

        <div className="flex-1 flex flex-col min-w-0">
          <div className="shrink-0 border-b border-default bg-app/70 backdrop-blur-sm sticky top-[var(--header-height)] z-20">
            <TabBar />
          </div>

          <main
            id="main-content"
            className="flex-1 min-w-0 px-4 sm:px-7 py-5 sm:py-7 animate-fade-in"
            tabIndex={-1}
          >
            {children}
          </main>
        </div>
      </div>
    </div>
  )
}
