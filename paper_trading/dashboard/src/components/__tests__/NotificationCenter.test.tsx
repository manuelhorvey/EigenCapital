import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { type Notification, type NotificationType } from '../../hooks/useNotificationCenter'
import NotificationCenter from '../NotificationCenter'

// ── Mock data ─────────────────────────────────────────────────────

const now = Date.now()

function makeNotifications(): Notification[] {
  return [
    { id: 'n1', type: 'error', title: 'Asset AUDUSD halted', message: 'Max drawdown exceeded', timestamp: now - 60_000, read: false },
    { id: 'n2', type: 'warning', title: 'PSI drift elevated', message: 'EURUSD model drift at 42%', timestamp: now - 120_000, read: false },
    { id: 'n3', type: 'warning', title: 'GBPUSD signal rejected', message: 'PEK budget limit', timestamp: now - 180_000, read: false },
    { id: 'n4', type: 'success', title: 'Engine reconnected', message: '', timestamp: now - 300_000, read: true },
    { id: 'n5', type: 'info', title: 'Weekly report generated', message: 'Week 28 summary ready', timestamp: now - 600_000, read: true },
  ]
}

// ── Mocks ─────────────────────────────────────────────────────────

const mockMarkRead = vi.fn()
const mockMarkAllRead = vi.fn()
const mockClear = vi.fn()

let mockNotifications = makeNotifications()
let mockUnreadCount = 3

// Desktop notification controls mock state
let mockBrowserSupported = false
let mockBrowserPermission: NotificationPermission = 'denied'
let mockBrowserEnabled = false
const mockSetEnabled = vi.fn()
const mockRequestPermission = vi.fn()
const mockBrowserNotify = vi.fn()

function resetMockState() {
  mockNotifications = makeNotifications()
  mockUnreadCount = 3
  mockMarkRead.mockClear()
  mockMarkAllRead.mockClear()
  mockClear.mockClear()
  mockBrowserSupported = false
  mockBrowserPermission = 'denied'
  mockBrowserEnabled = false
  mockSetEnabled.mockClear()
  mockRequestPermission.mockClear()
  mockBrowserNotify.mockClear()
}

vi.mock('../../hooks/useNotificationCenter', async () => {
  const actual = await vi.importActual('../../hooks/useNotificationCenter')
  return {
    ...actual,
    useNotificationCenter: () => ({
      notifications: mockNotifications,
      unreadCount: mockUnreadCount,
      add: vi.fn(),
      markRead: mockMarkRead,
      markAllRead: mockMarkAllRead,
      clear: mockClear,
    }),
  }
})

vi.mock('../../hooks/useBrowserNotifications', () => ({
  useBrowserNotifications: () => ({
    supported: mockBrowserSupported,
    permission: mockBrowserPermission,
    enabled: mockBrowserEnabled,
    setEnabled: mockSetEnabled,
    requestPermission: mockRequestPermission,
    notify: mockBrowserNotify,
  }),
  notifTag: (s: string) => `ec-notif-${s}`,
}))

vi.mock('../../hooks/useFocusTrap', () => ({
  default: () => ({ current: null }),
}))

// ── Helpers ───────────────────────────────────────────────────────

const onClose = vi.fn()

function setup(open = true) {
  onClose.mockClear()
  return render(<NotificationCenter open={open} onClose={onClose} />)
}

function getDialog() {
  return screen.queryByRole('dialog', { name: 'Notification center' })
}

// ── Tests ─────────────────────────────────────────────────────────

describe('NotificationCenter', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(now)
    resetMockState()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // ── Render / visibility ─────────────────────────────────────────

  it('renders nothing when open is false', () => {
    setup(false)
    expect(getDialog()).toBeNull()
  })

  it('renders the dialog with correct ARIA attributes when open is true', () => {
    setup()
    const dialog = getDialog()
    expect(dialog).toBeInTheDocument()
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveAttribute('aria-label', 'Notification center')
  })

  it('renders the backdrop overlay', () => {
    setup()
    const backdrop = document.querySelector('[aria-hidden="true"]')
    expect(backdrop).toBeInTheDocument()
  })

  // ── Empty state ─────────────────────────────────────────────────

  it('shows empty state with "No notifications yet" when there are no notifications', () => {
    mockNotifications = []
    mockUnreadCount = 0
    setup()
    expect(screen.getByText('No notifications yet')).toBeInTheDocument()
    expect(
      screen.getByText('System alerts, trade rejections, and status changes will appear here'),
    ).toBeInTheDocument()
  })

  it('shows contextual empty text when a filter has no matches', () => {
    mockNotifications = []
    mockUnreadCount = 0
    setup()

    // Switch to a specific filter — should show contextual empty state
    fireEvent.click(screen.getByText('Errors'))
    expect(screen.getByText('No error notifications')).toBeInTheDocument()
    expect(screen.getByText('Try switching to a different filter')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Info'))
    expect(screen.getByText('No info notifications')).toBeInTheDocument()
  })

  // ── Header ──────────────────────────────────────────────────────

  it('shows "Notifications" heading with Bell icon', () => {
    setup()
    expect(screen.getByText('Notifications')).toBeInTheDocument()
  })

  it('shows unread badge count in the header', () => {
    setup()
    // Badge is a span inside the header showing the unread count
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('hides unread badge when unreadCount is 0', () => {
    mockUnreadCount = 0
    setup()
    expect(screen.queryByText('3')).not.toBeInTheDocument()
  })

  it('shows "Mark all as read" button when there are unread notifications', () => {
    setup()
    expect(screen.getByLabelText('Mark all as read')).toBeInTheDocument()
  })

  it('hides "Mark all as read" button when all notifications are read', () => {
    mockUnreadCount = 0
    setup()
    expect(screen.queryByLabelText('Mark all as read')).not.toBeInTheDocument()
  })

  it('shows "Clear all notifications" button when there are any notifications', () => {
    setup()
    expect(screen.getByLabelText('Clear all notifications')).toBeInTheDocument()
  })

  it('hides "Clear all notifications" button when list is empty', () => {
    mockNotifications = []
    setup()
    expect(screen.queryByLabelText('Clear all notifications')).not.toBeInTheDocument()
  })

  // ── Close button ────────────────────────────────────────────────

  it('calls onClose when the X close button is clicked', () => {
    setup()
    fireEvent.click(screen.getByLabelText('Close notification center'))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('calls onClose when the Escape key is pressed', () => {
    setup()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('does not call onClose on other key presses', () => {
    setup()
    fireEvent.keyDown(window, { key: 'Enter' })
    expect(onClose).not.toHaveBeenCalled()
  })

  // ── Filter tabs ─────────────────────────────────────────────────

  it('renders all 5 severity filter tabs', () => {
    setup()
    const filters = ['All', 'Errors', 'Warnings', 'Success', 'Info']
    for (const label of filters) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('shows per-type counts on filter tabs', () => {
    setup()
    // Errors=1, Warnings=2, Success=1, Info=1
    // Each filter button has a child span with the count
    // The span is a sibling inside the button, not directly a text node
    expect(screen.getByText('Errors').closest('button')).toHaveTextContent(/Errors\s*1/)
    expect(screen.getByText('Warnings').closest('button')).toHaveTextContent(/Warnings\s*2/)
    expect(screen.getByText('Success').closest('button')).toHaveTextContent(/Success\s*1/)
    expect(screen.getByText('Info').closest('button')).toHaveTextContent(/Info\s*1/)
  })

  it('defaults to "All" filter showing all notifications', () => {
    setup()
    expect(screen.getByText('Asset AUDUSD halted')).toBeInTheDocument()
    expect(screen.getByText('Weekly report generated')).toBeInTheDocument()
  })

  it('filters by severity when a filter tab is clicked', () => {
    setup()

    // Click "Errors" — only error notification visible
    fireEvent.click(screen.getByText('Errors'))
    expect(screen.getByText('Asset AUDUSD halted')).toBeInTheDocument()
    expect(screen.queryByText('PSI drift elevated')).not.toBeInTheDocument()
    expect(screen.queryByText('Weekly report generated')).not.toBeInTheDocument()

    // Click "Success" — only success notification visible
    fireEvent.click(screen.getByText('Success'))
    expect(screen.getByText('Engine reconnected')).toBeInTheDocument()
    expect(screen.queryByText('Asset AUDUSD halted')).not.toBeInTheDocument()

    // Click "All" — all visible again
    fireEvent.click(screen.getByText('All'))
    expect(screen.getByText('Asset AUDUSD halted')).toBeInTheDocument()
    expect(screen.getByText('Weekly report generated')).toBeInTheDocument()
  })

  // ── Notification list ───────────────────────────────────────────

  it('renders all notifications with title, message, and timestamp', () => {
    setup()
    expect(screen.getByText('Asset AUDUSD halted')).toBeInTheDocument()
    expect(screen.getByText('Max drawdown exceeded')).toBeInTheDocument()
    expect(screen.getByText('1m ago')).toBeInTheDocument()

    expect(screen.getByText('Weekly report generated')).toBeInTheDocument()
    expect(screen.getByText('Week 28 summary ready')).toBeInTheDocument()
    expect(screen.getByText('10m ago')).toBeInTheDocument()
  })

  it('shows unread indicator (green dot) for unread notifications', () => {
    setup()
    // Unread notifications have a "Mark as read" button with green dot
    expect(screen.getByLabelText('Mark "Asset AUDUSD halted" as read')).toBeInTheDocument()
    expect(screen.getByLabelText('Mark "PSI drift elevated" as read')).toBeInTheDocument()
    expect(screen.getByLabelText('Mark "GBPUSD signal rejected" as read')).toBeInTheDocument()
  })

  it('does not show mark-as-read button for read notifications', () => {
    setup()
    expect(screen.queryByLabelText('Mark "Engine reconnected" as read')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Mark "Weekly report generated" as read')).not.toBeInTheDocument()
  })

  // ── Mark single as read ─────────────────────────────────────────

  it('calls markRead with the notification id when the green dot is clicked', () => {
    setup()
    fireEvent.click(screen.getByLabelText('Mark "Asset AUDUSD halted" as read'))
    expect(mockMarkRead).toHaveBeenCalledWith('n1')
    expect(mockMarkRead).toHaveBeenCalledOnce()
  })

  // ── Mark all as read ────────────────────────────────────────────

  it('calls markAllRead when the header button is clicked', () => {
    setup()
    fireEvent.click(screen.getByLabelText('Mark all as read'))
    expect(mockMarkAllRead).toHaveBeenCalledOnce()
  })

  // ── Clear all ───────────────────────────────────────────────────

  it('calls clear when the trash button is clicked', () => {
    setup()
    fireEvent.click(screen.getByLabelText('Clear all notifications'))
    expect(mockClear).toHaveBeenCalledOnce()
  })

  // ── Footer summary ──────────────────────────────────────────────

  it('shows total and unread count in the footer', () => {
    setup()
    const dialog = getDialog()!
    expect(dialog).toHaveTextContent('5 total')
    expect(dialog).toHaveTextContent('3 unread')
  })

  it('hides the footer when there are no notifications', () => {
    mockNotifications = []
    mockUnreadCount = 0
    setup()
    const dialog = getDialog()!
    expect(dialog).not.toHaveTextContent('total')
    expect(dialog).not.toHaveTextContent('unread')
  })

  // ── Relative timestamps ─────────────────────────────────────────

  it('shows "just now" for very recent notifications', () => {
    mockNotifications = [
      { id: 'fresh', type: 'info', title: 'Fresh notif', message: '', timestamp: now - 5_000, read: false },
    ]
    mockUnreadCount = 1
    setup()
    expect(screen.getByText('just now')).toBeInTheDocument()
  })

  it('shows "Xs ago" for seconds-old notifications', () => {
    mockNotifications = [
      { id: 'secs', type: 'info', title: 'Seconds old', message: '', timestamp: now - 45_000, read: false },
    ]
    mockUnreadCount = 1
    setup()
    expect(screen.getByText('just now')).toBeInTheDocument()
  })

  it('shows "Xm ago" for minutes-old notifications', () => {
    mockNotifications = [
      { id: 'mins', type: 'info', title: 'Minutes old', message: '', timestamp: now - 2 * 60_000, read: false },
    ]
    mockUnreadCount = 1
    setup()
    expect(screen.getByText('2m ago')).toBeInTheDocument()
  })

  it('shows "Xh ago" for hours-old notifications', () => {
    mockNotifications = [
      { id: 'hrs', type: 'info', title: 'Hours old', message: '', timestamp: now - 5 * 3_600_000, read: false },
    ]
    mockUnreadCount = 1
    setup()
    expect(screen.getByText('5h ago')).toBeInTheDocument()
  })

  it('shows "Xd ago" for days-old notifications', () => {
    mockNotifications = [
      { id: 'days', type: 'info', title: 'Days old', message: '', timestamp: now - 3 * 86_400_000, read: false },
    ]
    mockUnreadCount = 1
    setup()
    expect(screen.getByText('3d ago')).toBeInTheDocument()
  })

  // ── DesktopNotificationControls ────────────────────────────────

  describe('DesktopNotificationControls', () => {
    beforeEach(() => {
      // Ensure the dialog is open with at least one notification so the
      // footer area (where DesktopNotificationControls lives) renders.
      mockNotifications = makeNotifications()
      mockUnreadCount = 3
    })

    it('is hidden when the Notification API is not supported', () => {
      mockBrowserSupported = false
      setup()
      // The controls section is not rendered — look for the identifying
      // "Desktop notifications" label which should be absent
      expect(screen.queryByText('Desktop notifications')).not.toBeInTheDocument()
    })

    it('shows "Desktop notifications" label when supported', () => {
      mockBrowserSupported = true
      mockBrowserPermission = 'granted'
      mockBrowserEnabled = true
      setup()
      expect(screen.getByText('Desktop notifications')).toBeInTheDocument()
    })

    describe('when permission is default (needs request)', () => {
      beforeEach(() => {
        mockBrowserSupported = true
        mockBrowserPermission = 'default'
        mockBrowserEnabled = false
      })

      it('shows "off" status text', () => {
        setup()
        expect(screen.getByText('off')).toBeInTheDocument()
      })

      it('shows the Enable button to request permission', () => {
        setup()
        const enableBtn = screen.getByRole('button', { name: 'Enable' })
        expect(enableBtn).toBeInTheDocument()
      })

      it('calls requestPermission when Enable is clicked', () => {
        setup()
        fireEvent.click(screen.getByRole('button', { name: 'Enable' }))
        expect(mockRequestPermission).toHaveBeenCalledOnce()
      })

      it('shows explanatory text', () => {
        setup()
        expect(
          screen.getByText('Receive critical alerts even when this tab is not focused'),
        ).toBeInTheDocument()
      })

      it('does not show the toggle switch', () => {
        setup()
        // The toggle has role="switch" — it should not be present when
        // permission is default
        expect(screen.queryByRole('switch')).not.toBeInTheDocument()
      })
    })

    describe('when permission is granted and enabled', () => {
      beforeEach(() => {
        mockBrowserSupported = true
        mockBrowserPermission = 'granted'
        mockBrowserEnabled = true
      })

      it('shows "on" status text', () => {
        setup()
        expect(screen.getByText('on')).toBeInTheDocument()
      })

      it('shows the toggle switch with aria-checked="true"', () => {
        setup()
        const toggle = screen.getByRole('switch')
        expect(toggle).toBeInTheDocument()
        expect(toggle).toHaveAttribute('aria-checked', 'true')
      })

      it('toggle has correct aria-label', () => {
        setup()
        expect(
          screen.getByLabelText('Disable desktop notifications'),
        ).toBeInTheDocument()
      })

      it('shows descriptive text', () => {
        setup()
        expect(
          screen.getByText('Critical alerts and engine status changes will fire desktop notifications'),
        ).toBeInTheDocument()
      })

      it('clicking the toggle calls setEnabled(false)', () => {
        setup()
        fireEvent.click(screen.getByRole('switch'))
        expect(mockSetEnabled).toHaveBeenCalledWith(false)
        expect(mockSetEnabled).toHaveBeenCalledOnce()
      })
    })

    describe('when permission is granted but disabled', () => {
      beforeEach(() => {
        mockBrowserSupported = true
        mockBrowserPermission = 'granted'
        mockBrowserEnabled = false
      })

      it('shows "off" status text', () => {
        setup()
        expect(screen.getByText('off')).toBeInTheDocument()
      })

      it('shows the toggle switch with aria-checked="false"', () => {
        setup()
        const toggle = screen.getByRole('switch')
        expect(toggle).toBeInTheDocument()
        expect(toggle).toHaveAttribute('aria-checked', 'false')
      })

      it('toggle has "Enable" aria-label', () => {
        setup()
        expect(
          screen.getByLabelText('Enable desktop notifications'),
        ).toBeInTheDocument()
      })

      it('shows descriptive text', () => {
        setup()
        expect(
          screen.getByText('Desktop notifications are turned off'),
        ).toBeInTheDocument()
      })

      it('clicking the toggle calls setEnabled(true)', () => {
        setup()
        fireEvent.click(screen.getByRole('switch'))
        expect(mockSetEnabled).toHaveBeenCalledWith(true)
        expect(mockSetEnabled).toHaveBeenCalledOnce()
      })
    })

    describe('when permission is denied', () => {
      beforeEach(() => {
        mockBrowserSupported = true
        mockBrowserPermission = 'denied'
        mockBrowserEnabled = false
      })

      it('shows "blocked" status text', () => {
        setup()
        expect(screen.getByText('blocked')).toBeInTheDocument()
      })

      it('shows explanatory text about browser settings', () => {
        setup()
        expect(
          screen.getByText('Permission denied — update your browser site settings to enable'),
        ).toBeInTheDocument()
      })

      it('does not show toggle switch or Enable button', () => {
        setup()
        expect(screen.queryByRole('switch')).not.toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Enable' })).not.toBeInTheDocument()
      })
    })
  })
})
