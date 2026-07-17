import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { ThemeProvider } from '../../hooks/useTheme'
import TopBar from '../layout/TopBar'
import type { EngineHealth } from '../../hooks/useEngineHealth'

// ── Mock data types ──────────────────────────────────────────────

interface MockBundle {
  snapshot: {
    sequence_id: number | null
    emergency_halt: boolean
    engine_status: { last_update: string | null }
    assets: Record<string, unknown> | null
    portfolio: Record<string, unknown>
    halt_conditions: Record<string, unknown>
  }
  live: {
    mt5: {
      status: string
      account?: { portfolio_value: number } | null
    }
  }
}

function defaultBundle(): MockBundle {
  return {
    snapshot: {
      sequence_id: 42,
      emergency_halt: false,
      engine_status: { last_update: new Date().toISOString() },
      assets: { AUDUSD: {}, EURUSD: {} },
      portfolio: {},
      halt_conditions: {},
    },
    live: {
      mt5: { status: 'CONNECTED', account: { portfolio_value: 100_000 } },
    },
  }
}

// ── Mutable mock state ──────────────────────────────────────────

let mockUnreadCount = 0
let mockBundle: MockBundle = defaultBundle()
let mockHealthQuery: {
  isError: boolean
  isLoading: boolean
  data: EngineHealth | null | undefined
  error: Error | null
} = {
  isError: false,
  isLoading: false,
  data: {
    engine_alive: true,
    status: 'no_state',
    server_time: new Date().toISOString(),
    state_exists: false,
    state_file_age_s: -1,
    state_sequence_id: null,
  },
  error: null,
}

function resetMockState() {
  mockUnreadCount = 0
  mockBundle = defaultBundle()
  mockHealthQuery = {
    isError: false,
    isLoading: false,
    data: {
      engine_alive: true,
      status: 'no_state',
      server_time: new Date().toISOString(),
      state_exists: false,
      state_file_age_s: -1,
      state_sequence_id: null,
    },
    error: null,
  }
}

// ── Mocks ────────────────────────────────────────────────────────

vi.mock('../../hooks/useNotificationCenter', async () => {
  const actual = await vi.importActual('../../hooks/useNotificationCenter')
  return {
    ...actual,
    useNotificationCenter: () => ({
      notifications: [],
      unreadCount: mockUnreadCount,
      add: vi.fn(),
      markRead: vi.fn(),
      markAllRead: vi.fn(),
      clear: vi.fn(),
    }),
  }
})

vi.mock('../../hooks/useSidebarBadges', () => ({
  useSidebarBadges: () => ({}),
}))

vi.mock('../../hooks/useEngineHealth', () => ({
  useEngineHealth: () => mockHealthQuery,
}))

vi.mock('../../hooks/useSystemSnapshot', () => ({
  useSystemSnapshot: (select?: (data: unknown) => unknown) => ({
    data: select ? select(mockBundle) : mockBundle,
  }),
}))

vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual<object>('@tanstack/react-query')
  return {
    ...actual,
    useQueryClient: () => ({
      invalidateQueries: vi.fn().mockResolvedValue(undefined),
    }),
  }
})

// ── Helpers ──────────────────────────────────────────────────────

const onToggleNotifications = vi.fn()

function topBarTree(key?: string) {
  return (
    <BrowserRouter>
      <ThemeProvider>
        <TopBar onToggleNotifications={onToggleNotifications} key={key} />
      </ThemeProvider>
    </BrowserRouter>
  )
}

function renderTopBar() {
  onToggleNotifications.mockClear()
  return render(topBarTree())
}

function getBellButton() {
  return screen.queryByRole('button', { name: /notifications/i })
}

// ── Tests ────────────────────────────────────────────────────────

describe('TopBar', () => {
  beforeEach(() => {
    resetMockState()
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  // ── Notification bell ─────────────────────────────────────────

  describe('notification bell', () => {
    it('hides the badge when unreadCount is 0', () => {
      renderTopBar()
      const bell = getBellButton()
      expect(bell).toBeInTheDocument()
      expect(bell!.querySelector('span')).toBeNull()
    })

    it('shows the badge with the correct count when unreadCount is 1', () => {
      mockUnreadCount = 1
      renderTopBar()
      const bell = getBellButton()
      expect(bell).toBeInTheDocument()
      expect(bell).toHaveTextContent('1')
    })

    it('shows the badge with the correct count when unreadCount is 5', () => {
      mockUnreadCount = 5
      renderTopBar()
      const bell = getBellButton()
      expect(bell).toBeInTheDocument()
      expect(bell).toHaveTextContent('5')
    })

    it('shows "9+" when unreadCount exceeds 9', () => {
      mockUnreadCount = 15
      renderTopBar()
      const bell = getBellButton()
      expect(bell).toBeInTheDocument()
      expect(bell).toHaveTextContent('9+')
    })

    it('shows raw count "9" when unreadCount is exactly 9', () => {
      mockUnreadCount = 9
      renderTopBar()
      const bell = getBellButton()
      expect(bell).toHaveTextContent('9')
      expect(bell).not.toHaveTextContent('9+')
    })

    it('sets aria-label to "Notifications" when unreadCount is 0', () => {
      renderTopBar()
      expect(
        screen.getByRole('button', { name: 'Notifications' }),
      ).toBeInTheDocument()
    })

    it('sets aria-label to "Notifications (1 unread)" when unreadCount is 1', () => {
      mockUnreadCount = 1
      renderTopBar()
      expect(
        screen.getByRole('button', { name: 'Notifications (1 unread)' }),
      ).toBeInTheDocument()
    })

    it('updates badge and aria-label when unreadCount changes between renders', () => {
      const { rerender } = render(topBarTree('first'))
      expect(
        screen.getByRole('button', { name: 'Notifications' }),
      ).toBeInTheDocument()

      mockUnreadCount = 3
      rerender(topBarTree('second'))
      expect(
        screen.getByRole('button', { name: 'Notifications (3 unread)' }),
      ).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Notifications (3 unread)' })).toHaveTextContent('3')
    })

    it('does not show 9+ badge when transitioning from high to low count', () => {
      mockUnreadCount = 12
      const { rerender } = render(topBarTree('high'))
      expect(
        screen.getByRole('button', { name: 'Notifications (12 unread)' }),
      ).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Notifications (12 unread)' })).toHaveTextContent('9+')

      mockUnreadCount = 0
      rerender(topBarTree('zero'))
      expect(
        screen.getByRole('button', { name: 'Notifications' }),
      ).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Notifications' }).querySelector('span')).toBeNull()
    })
  })

  // ── Status ticker tokens ─────────────────────────────────────

  describe('status ticker tokens', () => {
    it('shows EC label and seq ID', () => {
      mockBundle.snapshot.sequence_id = 99
      renderTopBar()
      expect(screen.getByText('#99')).toBeInTheDocument()
    })

    it('does not show seq ID when sequence_id is null', () => {
      mockBundle.snapshot.sequence_id = null
      renderTopBar()
      expect(screen.queryByText(/#\d+/)).not.toBeInTheDocument()
    })

    // ── Engine state ───────────────────────────────────────────

    it('shows engine alive with green tone', () => {
      mockHealthQuery.data = { ...mockHealthQuery.data!, engine_alive: true }
      mockHealthQuery.isError = false
      renderTopBar()
      const el = screen.getByText('alive')
      expect(el).toBeInTheDocument()
      expect(el).toHaveClass('text-gov-green')
    })

    it('shows engine stale with yellow tone', () => {
      mockHealthQuery.data = { ...mockHealthQuery.data!, engine_alive: false }
      mockHealthQuery.isError = false
      renderTopBar()
      const el = screen.getByText('stale')
      expect(el).toBeInTheDocument()
      expect(el).toHaveClass('text-gov-yellow')
    })

    it('shows engine dead with red tone when isError is true', () => {
      mockHealthQuery.isError = true
      mockHealthQuery.data = undefined
      renderTopBar()
      const el = screen.getByText('dead')
      expect(el).toBeInTheDocument()
      expect(el).toHaveClass('text-gov-red')
    })

    // ── Tick age ───────────────────────────────────────────────

    it('shows tick age in seconds', () => {
      const recent = new Date().toISOString()
      mockBundle.snapshot.engine_status = { last_update: recent }
      renderTopBar()
      // tick age should be low (under 30s) with green tone
      const tickEl = screen.getByText(/\d+s/)
      expect(tickEl).toBeInTheDocument()
      expect(tickEl).toHaveClass('text-gov-green')
    })

    it('shows stale tick age with yellow tone', () => {
      const old = new Date(Date.now() - 90_000).toISOString()
      mockBundle.snapshot.engine_status = { last_update: old }
      renderTopBar()
      const tickEl = screen.getByText(/\d+s/)
      expect(tickEl).toBeInTheDocument()
      expect(tickEl).toHaveClass('text-gov-yellow')
    })

    it('shows old tick age with red tone', () => {
      const veryOld = new Date(Date.now() - 180_000).toISOString()
      mockBundle.snapshot.engine_status = { last_update: veryOld }
      renderTopBar()
      const tickEl = screen.getByText(/\d+s/)
      expect(tickEl).toBeInTheDocument()
      expect(tickEl).toHaveClass('text-gov-red')
    })

    it('does not show tick age when last_update is null', () => {
      mockBundle.snapshot.engine_status = { last_update: null }
      renderTopBar()
      expect(screen.queryByText(/^(\d+)s$/)).not.toBeInTheDocument()
    })

    // ── MT5 state ──────────────────────────────────────────────

    it('shows MT5 connected with equity and green tone', () => {
      mockBundle.live.mt5 = { status: 'CONNECTED', account: { portfolio_value: 100_000 } }
      renderTopBar()
      expect(screen.getByText('$100,000')).toBeInTheDocument()
    })

    it('shows MT5 connected with warn tone when equity is below 1000', () => {
      mockBundle.live.mt5 = { status: 'CONNECTED', account: { portfolio_value: 500 } }
      renderTopBar()
      const el = screen.getByText(/\$500/)
      expect(el).toBeInTheDocument()
      expect(el).toHaveClass('text-gov-yellow')
    })

    it('shows MT5 ERROR with red tone', () => {
      mockBundle.live.mt5 = { status: 'ERROR', account: null }
      renderTopBar()
      const el = screen.getByText('ERROR')
      expect(el).toBeInTheDocument()
      expect(el).toHaveClass('text-gov-red')
    })

    it('shows MT5 disconnected with warn tone', () => {
      mockBundle.live.mt5 = { status: 'DISCONNECTED', account: null }
      renderTopBar()
      const el = screen.getByText('disc')
      expect(el).toBeInTheDocument()
      expect(el).toHaveClass('text-gov-yellow')
    })

    it('shows MT5 unknown with muted tone', () => {
      mockBundle.live.mt5 = { status: 'UNKNOWN', account: null }
      renderTopBar()
      const el = screen.getByText('unknown')
      expect(el).toBeInTheDocument()
      expect(el).toHaveClass('text-tertiary')
    })

    // ── Halt indicator ─────────────────────────────────────────

    it('shows halt YES with red tone when emergency halt is active', () => {
      mockBundle.snapshot.emergency_halt = true
      renderTopBar()
      const el = screen.getByText('YES')
      expect(el).toBeInTheDocument()
      expect(el).toHaveClass('text-gov-red')
    })

    it('shows halt no with muted tone when not halted', () => {
      mockBundle.snapshot.emergency_halt = false
      renderTopBar()
      const el = screen.getByText('no')
      expect(el).toBeInTheDocument()
      expect(el).toHaveClass('text-tertiary')
    })

    it('sets assertive aria-live when halted', () => {
      mockBundle.snapshot.emergency_halt = true
      renderTopBar()
      expect(screen.getByLabelText('Top bar')).toHaveAttribute('aria-live', 'assertive')
    })

    it('sets polite aria-live when not halted', () => {
      mockBundle.snapshot.emergency_halt = false
      renderTopBar()
      expect(screen.getByLabelText('Top bar')).toHaveAttribute('aria-live', 'polite')
    })

    // ── Asset count ────────────────────────────────────────────

    it('shows asset count', () => {
      mockBundle.snapshot.assets = { AUDUSD: {}, EURUSD: {}, GBPUSD: {} }
      renderTopBar()
      expect(screen.getByText('3')).toBeInTheDocument()
    })

    it('does not show asset count when assets is null', () => {
      mockBundle.snapshot.assets = null
      renderTopBar()
      expect(screen.queryByText('2')).not.toBeInTheDocument()
    })

    // ── Halted asset badges ────────────────────────────────────

    it('shows pinned halted asset badges', () => {
      mockBundle.snapshot.assets = {
        AUDUSD: { halt: { halted: true } },
        EURUSD: { halt: { halted: false } },
        GBPUSD: { halt: { halted: true } },
      }
      renderTopBar()
      expect(screen.getByText('AUDUSD')).toBeInTheDocument()
      expect(screen.getByText('GBPUSD')).toBeInTheDocument()
      expect(screen.queryByText('EURUSD')).not.toBeInTheDocument()
    })

    it('does not show halted asset badges when no assets halted', () => {
      mockBundle.snapshot.assets = {
        AUDUSD: { halt: { halted: false } },
        EURUSD: {},
      }
      renderTopBar()
      expect(screen.queryByText('AUDUSD')).not.toBeInTheDocument()
      expect(screen.queryByText('EURUSD')).not.toBeInTheDocument()
    })
  })
})
