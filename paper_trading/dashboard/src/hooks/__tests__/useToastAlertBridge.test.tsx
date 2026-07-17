import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useToastAlertBridge } from '../useToastAlertBridge'
import type { Alert } from '../useMonitorAlerts'
import type { EngineHealth } from '../useEngineHealth'

// ── Mock data ─────────────────────────────────────────────────────

const mockToast = vi.fn()
const mockAddNotification = vi.fn()
const mockBrowserNotify = vi.fn()
const mockRequestPermission = vi.fn()

// Module-level mutable state — tests reassign these before render/rerender
let mockAlerts: Alert[] = []
let mockHealthQuery: {
  isError: boolean
  data: EngineHealth | null | undefined
} = {
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
let mockAdmission: {
  rejected: string[]
  rejection_reasons?: Record<string, string>
} | null = null

// ── Mocks ─────────────────────────────────────────────────────────

vi.mock('../useMonitorAlerts', () => ({
  useMonitorAlerts: () => mockAlerts,
}))

vi.mock('../useEngineHealth', () => ({
  useEngineHealth: () => mockHealthQuery,
}))

vi.mock('../useToast', () => ({
  useToast: () => ({
    toast: mockToast,
    toasts: [],
    dismiss: vi.fn(),
    clear: vi.fn(),
  }),
  ToastProvider: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}))

vi.mock('../useNotificationCenter', () => ({
  useNotificationCenter: () => ({
    add: mockAddNotification,
    notifications: [],
    unreadCount: 0,
    markRead: vi.fn(),
    markAllRead: vi.fn(),
    clear: vi.fn(),
  }),
  NotificationProvider: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}))

vi.mock('../useBrowserNotifications', () => ({
  useBrowserNotifications: () => ({
    supported: true,
    permission: 'granted' as NotificationPermission,
    enabled: true,
    setEnabled: vi.fn(),
    requestPermission: mockRequestPermission,
    notify: mockBrowserNotify,
  }),
  notifTag: (s: string) => `ec-notif-${s}`,
}))

vi.mock('../useSystemSnapshot', () => ({
  useSystemSnapshot: (_select?: unknown) => ({
    data: mockAdmission ? { admission: mockAdmission } : undefined,
  }),
}))

vi.mock('../../selectors/system', () => ({
  systemSelectors: {
    portfolio: (d: unknown) => d,
    snapshot: (d: unknown) => d?.snapshot,
    health: (d: unknown) => d?.live?.health,
    assets: (d: unknown) => d?.snapshot?.assets,
    engineStatus: (d: unknown) => d?.snapshot?.engine_status,
    mt5: (d: unknown) => d?.live?.mt5,
  },
  selectMeta: (d: unknown) => d?.meta,
  selectAsset: (_name: string) => (d: unknown) =>
    d?.snapshot?.assets?.[_name] ?? null,
  selectOpenPosition: (_name: string) => (d: unknown) =>
    d?.snapshot?.open_positions?.[_name] ?? null,
}))

// ── Helper ────────────────────────────────────────────────────────

/** Renders useToastAlertBridge via renderHook so refs persist across rerenders. */
function setup() {
  return renderHook(() => useToastAlertBridge())
}

function resetMocks() {
  mockToast.mockClear()
  mockAddNotification.mockClear()
  mockBrowserNotify.mockClear()
  mockRequestPermission.mockClear()
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
}

// ── Tests ─────────────────────────────────────────────────────────

describe('useToastAlertBridge', () => {
  beforeEach(() => {
    resetMocks()
  })

  // ── Monitor alerts ──────────────────────────────────────────────

  describe('monitor alerts', () => {
    it('fires toast + notification + desktop notify for a new critical alert', () => {
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

      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'error',
          title: 'AUDUSD halted',
          message: 'Max drawdown exceeded',
          duration: 6000,
        }),
      )
      expect(mockAddNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'error',
          title: 'AUDUSD halted',
          message: 'Max drawdown exceeded',
        }),
      )
      // Critical alerts always fire desktop notification with force:true
      expect(mockBrowserNotify).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'AUDUSD halted',
          body: 'Max drawdown exceeded',
          tag: 'ec-notif-alert-halt-audusd',
          force: true,
        }),
      )
    })

    it('fires toast + notification for a new warning alert (no desktop)', () => {
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

      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'warning',
          title: 'EURUSD health degraded',
          duration: 4000,
        }),
      )
      expect(mockAddNotification).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'warning', title: 'EURUSD health degraded' }),
      )
      // Warning alerts do NOT fire desktop notifications
      expect(mockBrowserNotify).not.toHaveBeenCalled()
    })

    it('does not re-fire for already-seen alert ids', () => {
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
      expect(mockToast).toHaveBeenCalledTimes(1) // first render fires
      mockToast.mockClear()
      mockAddNotification.mockClear()
      mockBrowserNotify.mockClear()

      // Rerender with same alerts — refs are preserved, should NOT re-fire
      rerender()
      expect(mockToast).not.toHaveBeenCalled()
      expect(mockAddNotification).not.toHaveBeenCalled()
      expect(mockBrowserNotify).not.toHaveBeenCalled()
    })

    it('fires for a new alert that appears alongside already-seen ones', () => {
      mockAlerts = [
        {
          id: 'existing',
          type: 'halt',
          asset: 'AUDUSD',
          severity: 'critical',
          message: 'Existing',
          timestamp: new Date().toISOString(),
        },
      ]
      const { rerender } = setup()
      expect(mockToast).toHaveBeenCalledTimes(1)
      mockToast.mockClear()
      mockAddNotification.mockClear()
      mockBrowserNotify.mockClear()

      // New alert added alongside the existing one
      mockAlerts = [
        {
          id: 'existing',
          type: 'halt',
          asset: 'AUDUSD',
          severity: 'critical',
          message: 'Existing',
          timestamp: new Date().toISOString(),
        },
        {
          id: 'new-one',
          type: 'health',
          asset: 'EURUSD',
          severity: 'critical',
          message: 'New critical',
          timestamp: new Date().toISOString(),
        },
      ]
      rerender()

      // Only the new alert should fire
      expect(mockToast).toHaveBeenCalledTimes(1)
      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'New critical' }),
      )
    })
  })

  // ── Engine health ───────────────────────────────────────────────

  describe('engine health', () => {
    it('fires on transition from alive to dead', () => {
      // Start with engine alive
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
      const { rerender } = setup()
      // First render: alive, previousDead=false, no fire
      expect(mockToast).not.toHaveBeenCalled()
      mockToast.mockClear()
      mockAddNotification.mockClear()
      mockBrowserNotify.mockClear()

      // Transition to dead
      mockHealthQuery = { isError: true, data: undefined }
      rerender()

      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'error',
          title: 'Engine connection lost',
          duration: 0,
        }),
      )
      expect(mockAddNotification).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'error', title: 'Engine connection lost' }),
      )
      expect(mockBrowserNotify).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'Engine connection lost', force: true }),
      )
    })

    it('fires on transition from dead to alive (reconnected)', () => {
      // Start with engine dead
      mockHealthQuery = { isError: true, data: undefined }
      const { rerender } = setup()
      // First render: dead, previousDead=false → fires engine-lost
      expect(mockToast).toHaveBeenCalledTimes(1)
      mockToast.mockClear()
      mockAddNotification.mockClear()
      mockBrowserNotify.mockClear()

      // Transition to alive
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
      rerender()

      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'success',
          title: 'Engine reconnected',
          duration: 3000,
        }),
      )
      expect(mockAddNotification).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'success', title: 'Engine reconnected' }),
      )
      expect(mockBrowserNotify).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'Engine reconnected' }),
      )
    })

    it('does not fire when health stays the same', () => {
      // Engine always dead
      mockHealthQuery = { isError: true, data: undefined }
      const { rerender } = setup()
      // First render fires because it transitions from null→dead
      expect(mockToast).toHaveBeenCalledTimes(1)
      mockToast.mockClear()
      mockAddNotification.mockClear()
      mockBrowserNotify.mockClear()

      // Still dead — should NOT fire
      rerender()
      expect(mockToast).not.toHaveBeenCalled()
      expect(mockAddNotification).not.toHaveBeenCalled()
      expect(mockBrowserNotify).not.toHaveBeenCalled()
    })
  })

  // ── PEK admission rejections ────────────────────────────────────

  describe('admission rejections', () => {
    it('fires toast + notification + desktop notify for each newly rejected asset', () => {
      mockAdmission = {
        rejected: ['AUDUSD', 'EURUSD'],
        rejection_reasons: { AUDUSD: 'Budget limit', EURUSD: 'Rank threshold' },
      }
      setup()

      // Two assets rejected → two calls each
      expect(mockToast).toHaveBeenCalledTimes(2)
      expect(mockAddNotification).toHaveBeenCalledTimes(2)
      expect(mockBrowserNotify).toHaveBeenCalledTimes(2)

      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'warning',
          title: 'AUDUSD signal rejected',
          duration: 5000,
        }),
      )
      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'warning', title: 'EURUSD signal rejected' }),
      )
      expect(mockBrowserNotify).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'AUDUSD signal rejected',
          tag: 'ec-notif-rejection-AUDUSD',
        }),
      )
      expect(mockBrowserNotify).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'EURUSD signal rejected',
          tag: 'ec-notif-rejection-EURUSD',
        }),
      )
    })

    it('falls back to default reason when rejection_reasons is missing', () => {
      mockAdmission = {
        rejected: ['GBPUSD'],
        rejection_reasons: {},
      }
      setup()

      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({ message: 'PEK budget/rank limit' }),
      )
    })

    it('does not fire when admission is null/undefined', () => {
      mockAdmission = null
      setup()

      expect(mockToast).not.toHaveBeenCalled()
      expect(mockAddNotification).not.toHaveBeenCalled()
      expect(mockBrowserNotify).not.toHaveBeenCalled()
    })

    it('does not re-fire for assets already seen in a previous cycle', () => {
      mockAdmission = {
        rejected: ['AUDUSD'],
        rejection_reasons: { AUDUSD: 'Budget limit' },
      }
      const { rerender } = setup()
      expect(mockToast).toHaveBeenCalledTimes(1)
      mockToast.mockClear()
      mockAddNotification.mockClear()
      mockBrowserNotify.mockClear()

      // Same assets rejected again — refs preserved, should NOT re-fire
      rerender()
      expect(mockToast).not.toHaveBeenCalled()
      expect(mockAddNotification).not.toHaveBeenCalled()
      expect(mockBrowserNotify).not.toHaveBeenCalled()
    })

    it('fires only for newly rejected assets when the set changes', () => {
      mockAdmission = {
        rejected: ['AUDUSD'],
        rejection_reasons: { AUDUSD: 'Budget limit' },
      }
      const { rerender } = setup()
      expect(mockToast).toHaveBeenCalledTimes(1)
      mockToast.mockClear()
      mockAddNotification.mockClear()
      mockBrowserNotify.mockClear()

      // AUDUSD still rejected but now EURUSD is also rejected
      mockAdmission = {
        rejected: ['AUDUSD', 'EURUSD'],
        rejection_reasons: { AUDUSD: 'Budget limit', EURUSD: 'Rank threshold' },
      }
      rerender()

      // Only EURUSD (the new one) should fire
      expect(mockToast).toHaveBeenCalledTimes(1)
      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'EURUSD signal rejected' }),
      )
    })
  })
})
