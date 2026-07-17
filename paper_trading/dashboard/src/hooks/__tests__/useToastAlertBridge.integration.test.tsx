import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { NotificationProvider, useNotificationCenter } from '../useNotificationCenter'
import { useToastAlertBridge } from '../useToastAlertBridge'
import type { Alert } from '../useMonitorAlerts'
import type { EngineHealth } from '../useEngineHealth'

// ── Mutable mock state (all data sources that feed into the bridge) ─

let mockAlerts: Alert[] = []
let mockHealthQuery: { isError: boolean; data: EngineHealth | null | undefined } = {
  isError: false,
  data: {
    status: 'ok' as const,
    server_time: '',
    state_exists: true,
    state_file_age_s: 0,
    state_sequence_id: 0,
    engine_alive: true,
  },
}
let mockAdmission: { rejected: string[]; rejection_reasons?: Record<string, string> } | null = null

const mockToast = vi.fn()
const mockBrowserNotify = vi.fn()

function resetMocks() {
  mockAlerts = []
  mockHealthQuery = {
    isError: false,
    data: {
      status: 'ok' as const,
      server_time: '',
      state_exists: true,
      state_file_age_s: 0,
      state_sequence_id: 0,
      engine_alive: true,
    },
  }
  mockAdmission = null
  mockToast.mockClear()
  mockBrowserNotify.mockClear()
}

// ── Mock external dependencies (everything except useNotificationCenter) ─

vi.mock('../useMonitorAlerts', () => ({
  useMonitorAlerts: () => mockAlerts,
}))

vi.mock('../useEngineHealth', () => ({
  useEngineHealth: () => mockHealthQuery,
}))

vi.mock('../useToast', () => ({
  useToast: () => ({ toast: mockToast, toasts: [], dismiss: vi.fn(), clear: vi.fn() }),
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../useBrowserNotifications', () => ({
  useBrowserNotifications: () => ({
    supported: true,
    permission: 'granted' as NotificationPermission,
    enabled: true,
    setEnabled: vi.fn(),
    requestPermission: vi.fn(),
    notify: mockBrowserNotify,
  }),
  notifTag: (s: string) => `ec-notif-${s}`,
}))

vi.mock('../useSystemSnapshot', () => ({
  useSystemSnapshot: (_select?: unknown) => {
    const data = mockAdmission ? { admission: mockAdmission } : undefined
    if (_select && data) return { data: _select(data) }
    if (_select) return { data: undefined }
    return { data }
  },
}))

vi.mock('../../selectors/system', () => ({
  systemSelectors: {
    portfolio: (d: unknown) => d,
    snapshot: (d: unknown) => d?.snapshot ?? {},
    health: (d: unknown) => d?.live?.health ?? { assets: {} },
    assets: (d: unknown) => d?.snapshot?.assets,
    engineStatus: (d: unknown) => d?.snapshot?.engine_status,
    mt5: (d: unknown) => d?.live?.mt5,
  },
  selectMeta: (d: unknown) => d?.meta,
  selectAsset: (_name: string) => (d: unknown) => d?.snapshot?.assets?.[_name] ?? null,
  selectOpenPosition: (_name: string) => (d: unknown) => d?.snapshot?.open_positions?.[_name] ?? null,
}))

// ── Test component ─────────────────────────────────────────────────

/**
 * Renders the real useToastAlertBridge (which fires into the real
 * NotificationProvider) alongside a display of all notifications
 * subscribed from the real useNotificationCenter hook.
 */
function BridgeTestApp() {
  useToastAlertBridge()
  const { notifications, unreadCount } = useNotificationCenter()

  return (
    <div data-testid="bridge-test">
      <span data-testid="unread-count">{unreadCount}</span>
      {notifications.length === 0 && <span data-testid="empty-state">No notifications</span>}
      {notifications.map(n => (
        <div key={n.id} className="notif-item">
          <span className="notif-title">{n.title}</span>
          <span className="notif-type">{n.type}</span>
        </div>
      ))}
    </div>
  )
}

function setup() {
  return render(
    <NotificationProvider>
      <BridgeTestApp />
    </NotificationProvider>,
  )
}

// ── Integration tests ─────────────────────────────────────────────

describe('useToastAlertBridge + NotificationProvider integration', () => {
  beforeEach(() => {
    resetMocks()
    sessionStorage.clear()
  })

  afterEach(() => {
    sessionStorage.clear()
  })

  // ── Monitor alerts ──────────────────────────────────────────────

  describe('monitor alerts', () => {
    it('adds a critical alert notification into the provider', () => {
      mockAlerts = [
        {
          id: 'halt-audusd',
          type: 'halt',
          asset: 'AUDUSD',
          severity: 'critical',
          message: 'AUDUSD halted',
          detail: 'Max drawdown exceeded',
          timestamp: new Date().toISOString(),
        },
      ]
      setup()

      expect(screen.getByText('AUDUSD halted')).toBeInTheDocument()
      expect(screen.getByText('error')).toBeInTheDocument()
      expect(screen.getByTestId('unread-count')).toHaveTextContent('1')
    })

    it('adds a warning alert notification into the provider', () => {
      mockAlerts = [
        {
          id: 'health-degraded',
          type: 'health',
          asset: 'EURUSD',
          severity: 'warning',
          message: 'EURUSD health degraded',
          timestamp: new Date().toISOString(),
        },
      ]
      setup()

      expect(screen.getByText('EURUSD health degraded')).toBeInTheDocument()
      expect(screen.getByText('warning')).toBeInTheDocument()
      expect(screen.getByTestId('unread-count')).toHaveTextContent('1')
    })

    it('adds notifications for multiple alerts at once', () => {
      mockAlerts = [
        {
          id: 'halt-audusd',
          type: 'halt',
          asset: 'AUDUSD',
          severity: 'critical',
          message: 'AUDUSD halted',
          timestamp: new Date().toISOString(),
        },
        {
          id: 'health-degraded',
          type: 'health',
          asset: 'EURUSD',
          severity: 'warning',
          message: 'EURUSD health degraded',
          timestamp: new Date().toISOString(),
        },
      ]
      setup()

      expect(screen.getByText('AUDUSD halted')).toBeInTheDocument()
      expect(screen.getByText('EURUSD health degraded')).toBeInTheDocument()
      expect(screen.getByTestId('unread-count')).toHaveTextContent('2')
    })

    it('does not re-add an alert that was already seen in a previous cycle', () => {
      mockAlerts = [
        {
          id: 'halt-audusd',
          type: 'halt',
          asset: 'AUDUSD',
          severity: 'critical',
          message: 'AUDUSD halted',
          timestamp: new Date().toISOString(),
        },
      ]
      const { rerender } = setup()

      expect(screen.getByText('AUDUSD halted')).toBeInTheDocument()
      expect(screen.getByTestId('unread-count')).toHaveTextContent('1')

      // Rerender with same alerts — bridge refs preserved, no duplicate
      rerender(
        <NotificationProvider>
          <BridgeTestApp />
        </NotificationProvider>,
      )

      expect(screen.getByText('AUDUSD halted')).toBeInTheDocument()
      expect(screen.getByTestId('unread-count')).toHaveTextContent('1')
    })
  })

  // ── Engine health ───────────────────────────────────────────────

  describe('engine health', () => {
    it('adds "Engine connection lost" notification when engine transitions to dead', () => {
      mockHealthQuery = { isError: true, data: undefined }
      setup()

      expect(screen.getByText('Engine connection lost')).toBeInTheDocument()
      expect(screen.getByText('error')).toBeInTheDocument()
      expect(screen.getByTestId('unread-count')).toHaveTextContent('1')
    })

    it('shows empty state when engine is alive from the start', () => {
      mockHealthQuery = {
        isError: false,
        data: {
          status: 'ok' as const,
          server_time: '',
          state_exists: true,
          state_file_age_s: 0,
          state_sequence_id: 0,
          engine_alive: true,
        },
      }
      setup()

      expect(screen.getByTestId('empty-state')).toBeInTheDocument()
    })

    it('tracks engine-lost → reconnected transition cycle via rerender', () => {
      // Start: engine dead
      mockHealthQuery = { isError: true, data: undefined }
      const { rerender } = setup()

      // engine-lost fires on first render (null→dead transition)
      expect(screen.getByText('Engine connection lost')).toBeInTheDocument()
      expect(screen.getByTestId('unread-count')).toHaveTextContent('1')

      // Transition: dead → alive
      mockHealthQuery = {
        isError: false,
        data: {
          status: 'ok' as const,
          server_time: '',
          state_exists: true,
          state_file_age_s: 0,
          state_sequence_id: 0,
          engine_alive: true,
        },
      }
      rerender(
        <NotificationProvider>
          <BridgeTestApp />
        </NotificationProvider>,
      )

      // Both present: engine-lost + reconnected
      expect(screen.getByText('Engine connection lost')).toBeInTheDocument()
      expect(screen.getByText('Engine reconnected')).toBeInTheDocument()
      expect(screen.getByTestId('unread-count')).toHaveTextContent('2')
    })

    it('does not add duplicate engine-lost when health stays dead across rerenders', () => {
      mockHealthQuery = { isError: true, data: undefined }
      const { rerender } = setup()

      expect(screen.getByText('Engine connection lost')).toBeInTheDocument()
      expect(screen.getByTestId('unread-count')).toHaveTextContent('1')

      // Still dead — no duplicate
      rerender(
        <NotificationProvider>
          <BridgeTestApp />
        </NotificationProvider>,
      )

      expect(screen.getByText('Engine connection lost')).toBeInTheDocument()
      expect(screen.getByTestId('unread-count')).toHaveTextContent('1')
    })
  })

  // ── PEK admission rejections ────────────────────────────────────

  describe('PEK admission rejections', () => {
    it('adds rejection notifications for newly rejected assets', () => {
      mockAdmission = {
        rejected: ['AUDUSD', 'EURUSD'],
        rejection_reasons: { AUDUSD: 'Budget limit', EURUSD: 'Rank threshold' },
      }
      setup()

      expect(screen.getByText('AUDUSD signal rejected')).toBeInTheDocument()
      expect(screen.getByText('EURUSD signal rejected')).toBeInTheDocument()
      expect(screen.getAllByText('warning')).toHaveLength(2)
      expect(screen.getByTestId('unread-count')).toHaveTextContent('2')
    })

    it('falls back to default reason when rejection_reasons is missing', () => {
      mockAdmission = {
        rejected: ['GBPUSD'],
        rejection_reasons: {},
      }
      setup()

      expect(screen.getByText('GBPUSD signal rejected')).toBeInTheDocument()
      expect(screen.getByTestId('unread-count')).toHaveTextContent('1')
    })

    it('does not add notifications when admission is null', () => {
      mockAdmission = null
      setup()
      expect(screen.getByTestId('empty-state')).toBeInTheDocument()
    })

    it('does not re-fire for assets already rejected in a previous cycle', () => {
      mockAdmission = {
        rejected: ['AUDUSD'],
        rejection_reasons: { AUDUSD: 'Budget limit' },
      }
      const { rerender } = setup()

      expect(screen.getByText('AUDUSD signal rejected')).toBeInTheDocument()
      expect(screen.getByTestId('unread-count')).toHaveTextContent('1')

      rerender(
        <NotificationProvider>
          <BridgeTestApp />
        </NotificationProvider>,
      )

      expect(screen.getByText('AUDUSD signal rejected')).toBeInTheDocument()
      expect(screen.getByTestId('unread-count')).toHaveTextContent('1')
    })

    it('adds notification only for newly rejected assets when the set changes', () => {
      mockAdmission = {
        rejected: ['AUDUSD'],
        rejection_reasons: { AUDUSD: 'Budget limit' },
      }
      const { rerender } = setup()

      expect(screen.getByText('AUDUSD signal rejected')).toBeInTheDocument()
      expect(screen.getByTestId('unread-count')).toHaveTextContent('1')

      // EURUSD joins the rejected set
      mockAdmission = {
        rejected: ['AUDUSD', 'EURUSD'],
        rejection_reasons: { AUDUSD: 'Budget limit', EURUSD: 'Rank threshold' },
      }
      rerender(
        <NotificationProvider>
          <BridgeTestApp />
        </NotificationProvider>,
      )

      expect(screen.getByText('AUDUSD signal rejected')).toBeInTheDocument()
      expect(screen.getByText('EURUSD signal rejected')).toBeInTheDocument()
      expect(screen.getByTestId('unread-count')).toHaveTextContent('2')
    })
  })

  // ── Combined flows ──────────────────────────────────────────────

  describe('combined flows', () => {
    it('handles alerts + engine health + admission rejections simultaneously', () => {
      mockAlerts = [
        {
          id: 'halt-critical',
          type: 'halt',
          asset: 'AUDUSD',
          severity: 'critical',
          message: 'AUDUSD halted',
          timestamp: new Date().toISOString(),
        },
      ]
      mockHealthQuery = { isError: true, data: undefined }
      mockAdmission = {
        rejected: ['EURUSD'],
        rejection_reasons: { EURUSD: 'Rank threshold' },
      }
      setup()

      expect(screen.getByText('AUDUSD halted')).toBeInTheDocument()
      expect(screen.getByText('Engine connection lost')).toBeInTheDocument()
      expect(screen.getByText('EURUSD signal rejected')).toBeInTheDocument()
      expect(screen.getByTestId('unread-count')).toHaveTextContent('3')
    })
  })
})
