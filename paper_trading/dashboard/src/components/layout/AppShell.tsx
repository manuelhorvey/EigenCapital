import { useState, useCallback, useRef, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { useSystemSnapshot } from '../../hooks/useSystemSnapshot'
import { useSnapshotReconciler } from '../../hooks/useSnapshotReconciler'
import { useSystemIntegrity } from '../../hooks/useSystemIntegrity'
import { useSelectedAsset } from '../../hooks/useSelectedAsset'
import { SystemDegradedBanner } from '../ui/SystemDegradedBanner'
import ErrorScreen from '../ui/ErrorScreen'
import PageTransition from '../ui/PageTransition'
import Sidebar from './Sidebar'
import TopBar from './TopBar'
import TabBar from './TabBar'
import EmergencyHaltBanner from '../EmergencyHaltBanner'
import KeyboardShortcuts from './KeyboardShortcuts'
import CommandPalette from '../CommandPalette'
import NotificationCenter from '../NotificationCenter'
import { PAGE_CONTAINER } from '../../design/grid'

interface AppShellProps {
  children: ReactNode
}

/** Root layout wrapping all pages. Renders ticker rail, sidebar, tab bar, and content. @param {{ children: ReactNode }} props */
export default function AppShell({ children }: AppShellProps) {
  const mainId = 'main-content'
  const mainRef = useRef<HTMLElement>(null)
  const location = useLocation()
  const { data: bundle } = useSystemSnapshot()
  useSnapshotReconciler(bundle)
  const integrity = useSystemIntegrity(bundle)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [notifCenterOpen, setNotifCenterOpen] = useState(false)
  const toggleSidebar = useCallback(() => setSidebarOpen(prev => !prev), [])
  const closeSidebar = useCallback(() => setSidebarOpen(false), [])
  const toggleNotifications = useCallback(() => setNotifCenterOpen(prev => !prev), [])
  const closeNotifications = useCallback(() => setNotifCenterOpen(false), [])
  const { setSelectedAsset } = useSelectedAsset()

  // Extract asset names from snapshot for command palette search
  const assetNames = bundle?.snapshot?.assets
    ? Object.keys(bundle.snapshot.assets).sort()
    : []

  // Focus main content after page transitions complete (WCAG 2.4.3)
  const focusMain = useCallback(() => {
    // Only move focus if it's currently on the body or an unknown element
    const active = document.activeElement
    if (!active || active === document.body) {
      mainRef.current?.focus()
    }
  }, [])

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

  // Context actions slot for per-page action buttons in the TopBar.
  // Phase 3 will wire this to a context provider so pages can register
  // custom actions (e.g. "Export CSV" on Reports, "Add Filter" on Trading).
  const pageContextActions: React.ReactNode = null

  return (
    <div className="min-h-screen bg-app text-secondary flex flex-col">
      <a href={`#${mainId}`} className="skip-link">Skip to main content</a>
      <TopBar onToggleSidebar={toggleSidebar} onToggleNotifications={toggleNotifications} contextActions={pageContextActions} />
      <TabBar />
      <SystemDegradedBanner integrity={integrity} />
      <EmergencyHaltBanner />

      <div className={`flex-1 flex relative ${PAGE_CONTAINER}`}>
        <Sidebar open={sidebarOpen} onClose={closeSidebar} />

        <div className="flex-1 flex flex-col min-w-0">

          <main id={mainId} ref={mainRef} tabIndex={-1} className="flex-1 min-w-0 px-4 sm:px-7 py-5 sm:py-7 outline-none" role="main" aria-label="Dashboard content">
            <PageTransition locationKey={location.pathname} onVisible={focusMain}>
              {children}
            </PageTransition>
          </main>

          <KeyboardShortcuts />
          <CommandPalette
            assetNames={assetNames}
            onSelectAsset={setSelectedAsset}
            assets={
              bundle?.snapshot?.assets as Record<string, { signal?: string; confidence?: number; price?: number }> | undefined
            }
          />
          <NotificationCenter open={notifCenterOpen} onClose={closeNotifications} />
        </div>
      </div>
    </div>
  )
}
