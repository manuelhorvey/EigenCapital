import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { useCallback } from 'react'
import {
  NotificationProvider,
  useNotificationCenter,
  type NotificationType,
} from '../../hooks/useNotificationCenter'
import NotificationCenter from '../NotificationCenter'

// ── Mocks (non-NotificationCenter dependencies only) ──────────────

let mockBrowserSupported = false
let mockBrowserPermission: NotificationPermission = 'denied'
let mockBrowserEnabled = false
const mockSetEnabled = vi.fn()
const mockRequestPermission = vi.fn()

function resetDesktopMock() {
  mockBrowserSupported = false
  mockBrowserPermission = 'denied'
  mockBrowserEnabled = false
  mockSetEnabled.mockClear()
  mockRequestPermission.mockClear()
}

vi.mock('../../hooks/useBrowserNotifications', () => ({
  useBrowserNotifications: () => ({
    supported: mockBrowserSupported,
    permission: mockBrowserPermission,
    enabled: mockBrowserEnabled,
    setEnabled: mockSetEnabled,
    requestPermission: mockRequestPermission,
    notify: vi.fn(),
  }),
  notifTag: (s: string) => `ec-notif-${s}`,
}))

vi.mock('../../hooks/useFocusTrap', () => ({
  default: () => ({ current: null }),
}))

// ── Test helpers ──────────────────────────────────────────────────

/** Exposes add() via a button so tests trigger real provider adds. */
function AddNotificationButton({
  type,
  title,
  message,
}: {
  type: NotificationType
  title: string
  message?: string
}) {
  const { add } = useNotificationCenter()
  const handleClick = useCallback(() => {
    add({ type, title, message })
  }, [add, type, title, message])
  return (
    <button type="button" onClick={handleClick} data-testid={`add-${type}`}>
      Add {type}: {title}
    </button>
  )
}

interface TestAppProps {
  open?: boolean
  onClose?: () => void
}

function TestApp({ open = true, onClose = vi.fn() }: TestAppProps) {
  return (
    <NotificationProvider>
      <div data-testid="test-app">
        <AddNotificationButton type="error" title="Engine failure" message="AUDUSD engine crashed" />
        <AddNotificationButton type="warning" title="Drawdown limit" message="Portfolio at 12% DD" />
        <AddNotificationButton type="success" title="Model retrained" message="GBPUSD model refreshed" />
        <AddNotificationButton type="info" title="Market closed" message="Weekend market closure" />
      </div>
      <NotificationCenter open={open} onClose={onClose} />
    </NotificationProvider>
  )
}

/** Returns the header badge (pill next to "Notifications"), or null. */
function findHeaderBadge(): HTMLElement | null {
  const heading = screen.queryByText('Notifications')
  if (!heading) return null
  const headerRow = heading.closest('[class*="items-center"]')
  if (!headerRow) return null
  const badge = headerRow.querySelector('[class*="rounded-full"]')
  return badge as HTMLElement | null
}

function setup(open = true) {
  const onClose = vi.fn()
  const view = render(<TestApp open={open} onClose={onClose} />)
  return { onClose, view }
}

function getDialog() {
  return screen.queryByRole('dialog', { name: 'Notification center' })
}

// ── Dedup test helpers (children of NotificationProvider) ─────────

function DedupControls() {
  const { add } = useNotificationCenter()
  return (
    <>
      <button type="button" data-testid="add-fixed" onClick={() => add({ type: 'error', title: 'Dup', id: 'fixed-id' })}>
        Add with fixed ID
      </button>
      <button type="button" data-testid="add-unique" onClick={() => add({ type: 'warning', title: 'Unique' })}>
        Add unique
      </button>
    </>
  )
}

function DedupTestApp() {
  const onClose = vi.fn()
  return (
    <NotificationProvider>
      <DedupControls />
      <NotificationCenter open onClose={onClose} />
    </NotificationProvider>
  )
}

// ── Integration tests ────────────────────────────────────────────

describe('NotificationCenter + NotificationProvider integration', () => {
  beforeEach(() => {
    sessionStorage.clear()
    resetDesktopMock()
  })

  afterEach(() => {
    sessionStorage.clear()
  })

  // ── Adding via provider ───────────────────────────────────────

  describe('adding notifications via provider', () => {
    it('renders empty state when no notifications have been added', () => {
      setup()
      expect(screen.getByText('No notifications yet')).toBeInTheDocument()
    })

    it('shows an error notification after clicking the error add button', () => {
      setup()
      fireEvent.click(screen.getByTestId('add-error'))
      expect(screen.getByText('Engine failure')).toBeInTheDocument()
      expect(screen.getByText('AUDUSD engine crashed')).toBeInTheDocument()
    })

    it('shows all added notifications in the panel', () => {
      setup()
      fireEvent.click(screen.getByTestId('add-error'))
      fireEvent.click(screen.getByTestId('add-warning'))
      fireEvent.click(screen.getByTestId('add-success'))
      fireEvent.click(screen.getByTestId('add-info'))

      expect(screen.getByText('Engine failure')).toBeInTheDocument()
      expect(screen.getByText('Drawdown limit')).toBeInTheDocument()
      expect(screen.getByText('Model retrained')).toBeInTheDocument()
      expect(screen.getByText('Market closed')).toBeInTheDocument()
    })

    it('updates the unread badge count as notifications are added', () => {
      setup()

      expect(findHeaderBadge()).toBeNull()

      fireEvent.click(screen.getByTestId('add-error'))
      expect(findHeaderBadge()).toHaveTextContent('1')

      fireEvent.click(screen.getByTestId('add-warning'))
      expect(findHeaderBadge()).toHaveTextContent('2')
    })

    it('shows per-type filter counts after adding notifications', () => {
      setup()
      fireEvent.click(screen.getByTestId('add-error'))
      fireEvent.click(screen.getByTestId('add-warning'))
      fireEvent.click(screen.getByTestId('add-info'))

      const errorBtn = screen.getByText('Errors').closest('button')!
      const warningBtn = screen.getByText('Warnings').closest('button')!
      const infoBtn = screen.getByText('Info').closest('button')!

      expect(errorBtn).toHaveTextContent(/Errors\s*1/)
      expect(warningBtn).toHaveTextContent(/Warnings\s*1/)
      expect(infoBtn).toHaveTextContent(/Info\s*1/)
    })

    it('deduplicates notifications with the same ID', () => {
      render(<DedupTestApp />)

      fireEvent.click(screen.getByTestId('add-fixed'))
      expect(screen.getByText('Dup')).toBeInTheDocument()

      const errorBtn = screen.getByText('Errors').closest('button')!
      expect(errorBtn).toHaveTextContent(/Errors\s*1/)

      fireEvent.click(screen.getByTestId('add-fixed'))
      expect(errorBtn).toHaveTextContent(/Errors\s*1/)

      fireEvent.click(screen.getByTestId('add-unique'))
      expect(screen.getByText('Unique')).toBeInTheDocument()
      const warningBtn = screen.getByText('Warnings').closest('button')!
      expect(warningBtn).toHaveTextContent(/Warnings\s*1/)
      expect(errorBtn).toHaveTextContent(/Errors\s*1/)
    })
  })

  // ── Marking as read ──────────────────────────────────────────

  describe('marking notifications as read', () => {
    it('marks a single notification as read by clicking the green dot', () => {
      setup()
      fireEvent.click(screen.getByTestId('add-error'))

      const markBtn = screen.getByLabelText('Mark "Engine failure" as read')
      expect(markBtn).toBeInTheDocument()
      fireEvent.click(markBtn)
      expect(
        screen.queryByLabelText('Mark "Engine failure" as read'),
      ).not.toBeInTheDocument()
    })

    it('updates the unread badge after marking a notification as read', () => {
      setup()
      fireEvent.click(screen.getByTestId('add-error'))
      fireEvent.click(screen.getByTestId('add-warning'))

      expect(screen.getByText('2')).toBeInTheDocument()

      fireEvent.click(screen.getByLabelText('Mark "Engine failure" as read'))

      expect(findHeaderBadge()).toHaveTextContent('1')
    })

    it('marks all notifications as read via the Mark all as read button', () => {
      setup()
      fireEvent.click(screen.getByTestId('add-error'))
      fireEvent.click(screen.getByTestId('add-warning'))
      fireEvent.click(screen.getByTestId('add-success'))

      expect(
        screen.getByLabelText('Mark "Engine failure" as read'),
      ).toBeInTheDocument()
      expect(
        screen.getByLabelText('Mark "Drawdown limit" as read'),
      ).toBeInTheDocument()
      expect(
        screen.getByLabelText('Mark "Model retrained" as read'),
      ).toBeInTheDocument()

      fireEvent.click(screen.getByLabelText('Mark all as read'))

      expect(
        screen.queryByLabelText('Mark "Engine failure" as read'),
      ).not.toBeInTheDocument()
      expect(
        screen.queryByLabelText('Mark "Drawdown limit" as read'),
      ).not.toBeInTheDocument()
      expect(
        screen.queryByLabelText('Mark "Model retrained" as read'),
      ).not.toBeInTheDocument()

      expect(findHeaderBadge()).toBeNull()
    })

    it('hides "Mark all as read" button when all notifications are read', () => {
      setup()
      fireEvent.click(screen.getByTestId('add-error'))

      expect(screen.getByLabelText('Mark all as read')).toBeInTheDocument()

      fireEvent.click(screen.getByLabelText('Mark "Engine failure" as read'))

      expect(
        screen.queryByLabelText('Mark all as read'),
      ).not.toBeInTheDocument()
    })
  })

  // ── Filtering ────────────────────────────────────────────────

  describe('filtering', () => {
    it('filters notifications by type when a filter tab is clicked', () => {
      setup()
      fireEvent.click(screen.getByTestId('add-error'))
      fireEvent.click(screen.getByTestId('add-warning'))

      expect(screen.getByText('Engine failure')).toBeInTheDocument()
      expect(screen.getByText('Drawdown limit')).toBeInTheDocument()

      fireEvent.click(screen.getByText('Errors'))
      expect(screen.getByText('Engine failure')).toBeInTheDocument()
      expect(screen.queryByText('Drawdown limit')).not.toBeInTheDocument()

      fireEvent.click(screen.getByText('Warnings'))
      expect(screen.queryByText('Engine failure')).not.toBeInTheDocument()
      expect(screen.getByText('Drawdown limit')).toBeInTheDocument()
    })

    it('shows contextual empty state when filter has no matches', () => {
      setup()
      fireEvent.click(screen.getByTestId('add-error'))

      fireEvent.click(screen.getByText('Success'))
      expect(screen.getByText('No success notifications')).toBeInTheDocument()
      expect(
        screen.getByText('Try switching to a different filter'),
      ).toBeInTheDocument()
    })
  })

  // ── Clear ────────────────────────────────────────────────────

  describe('clear', () => {
    it('clears all notifications and shows empty state', () => {
      setup()
      fireEvent.click(screen.getByTestId('add-error'))
      fireEvent.click(screen.getByTestId('add-warning'))

      expect(screen.getByText('Engine failure')).toBeInTheDocument()

      fireEvent.click(screen.getByLabelText('Clear all notifications'))

      expect(screen.getByText('No notifications yet')).toBeInTheDocument()
      expect(screen.queryByText('Engine failure')).not.toBeInTheDocument()
      expect(screen.queryByText('Drawdown limit')).not.toBeInTheDocument()
    })

    it('hides the Clear button after clearing all notifications', () => {
      setup()
      fireEvent.click(screen.getByTestId('add-error'))

      expect(
        screen.getByLabelText('Clear all notifications'),
      ).toBeInTheDocument()

      fireEvent.click(screen.getByLabelText('Clear all notifications'))

      expect(
        screen.queryByLabelText('Clear all notifications'),
      ).not.toBeInTheDocument()
    })
  })

  // ── Footer summary ───────────────────────────────────────────

  describe('footer summary', () => {
    it('shows total and unread counts in the footer', () => {
      setup()
      fireEvent.click(screen.getByTestId('add-error'))
      fireEvent.click(screen.getByTestId('add-warning'))

      const dialog = getDialog()!
      expect(dialog).toHaveTextContent('2 total')
      expect(dialog).toHaveTextContent('2 unread')

      fireEvent.click(screen.getByLabelText('Mark "Engine failure" as read'))

      expect(dialog).toHaveTextContent('2 total')
      expect(dialog).toHaveTextContent('1 unread')
    })
  })

  // ── Close panel ──────────────────────────────────────────────

  describe('closing the panel', () => {
    it('calls onClose when the X button is clicked', () => {
      const { onClose } = setup()
      fireEvent.click(screen.getByLabelText('Close notification center'))
      expect(onClose).toHaveBeenCalledOnce()
    })

    it('calls onClose when Escape key is pressed', () => {
      const { onClose } = setup()
      fireEvent.keyDown(window, { key: 'Escape' })
      expect(onClose).toHaveBeenCalledOnce()
    })
  })

  // ── DesktopNotificationControls ─────────────────────────────

  describe('DesktopNotificationControls', () => {
    /** Render the test app with current mock values and add one notification. */
    function desktopSetup() {
      setup()
      fireEvent.click(screen.getByTestId('add-error'))
    }

    describe('hidden when unsupported', () => {
      it('is hidden when the Notification API is not supported', () => {
        mockBrowserSupported = false
        desktopSetup()
        expect(screen.queryByText('Desktop notifications')).not.toBeInTheDocument()
      })
    })

    describe('when permission is default (needs request)', () => {
      beforeEach(() => {
        mockBrowserSupported = true
        mockBrowserPermission = 'default'
        mockBrowserEnabled = false
        desktopSetup()
      })

      it('shows "Desktop notifications" label and "off" status', () => {
        expect(screen.getByText('Desktop notifications')).toBeInTheDocument()
        expect(screen.getByText('off')).toBeInTheDocument()
      })

      it('shows the Enable button to request permission', () => {
        expect(
          screen.getByRole('button', { name: 'Enable' }),
        ).toBeInTheDocument()
      })

      it('calls requestPermission when Enable is clicked', () => {
        fireEvent.click(screen.getByRole('button', { name: 'Enable' }))
        expect(mockRequestPermission).toHaveBeenCalledOnce()
      })

      it('does not show the toggle switch', () => {
        expect(screen.queryByRole('switch')).not.toBeInTheDocument()
      })

      it('shows explanatory text about receiving alerts', () => {
        expect(
          screen.getByText('Receive critical alerts even when this tab is not focused'),
        ).toBeInTheDocument()
      })
    })

    describe('when permission is granted and enabled', () => {
      beforeEach(() => {
        mockBrowserSupported = true
        mockBrowserPermission = 'granted'
        mockBrowserEnabled = true
        desktopSetup()
      })

      it('shows "on" status', () => {
        expect(screen.getByText('on')).toBeInTheDocument()
      })

      it('shows the toggle switch with aria-checked="true"', () => {
        const toggle = screen.getByRole('switch')
        expect(toggle).toBeInTheDocument()
        expect(toggle).toHaveAttribute('aria-checked', 'true')
      })

      it('toggle has "Disable desktop notifications" label', () => {
        expect(
          screen.getByLabelText('Disable desktop notifications'),
        ).toBeInTheDocument()
      })

      it('shows descriptive text about critical alerts', () => {
        expect(
          screen.getByText('Critical alerts and engine status changes will fire desktop notifications'),
        ).toBeInTheDocument()
      })

      it('clicking the toggle calls setEnabled(false)', () => {
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
        desktopSetup()
      })

      it('shows "off" status', () => {
        expect(screen.getByText('off')).toBeInTheDocument()
      })

      it('shows the toggle switch with aria-checked="false"', () => {
        const toggle = screen.getByRole('switch')
        expect(toggle).toBeInTheDocument()
        expect(toggle).toHaveAttribute('aria-checked', 'false')
      })

      it('toggle has "Enable desktop notifications" label', () => {
        expect(
          screen.getByLabelText('Enable desktop notifications'),
        ).toBeInTheDocument()
      })

      it('shows descriptive text about being turned off', () => {
        expect(
          screen.getByText('Desktop notifications are turned off'),
        ).toBeInTheDocument()
      })

      it('clicking the toggle calls setEnabled(true)', () => {
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
        desktopSetup()
      })

      it('shows "blocked" status and explanatory text', () => {
        expect(screen.getByText('blocked')).toBeInTheDocument()
        expect(
          screen.getByText('Permission denied — update your browser site settings to enable'),
        ).toBeInTheDocument()
      })

      it('does not show toggle switch or Enable button', () => {
        expect(screen.queryByRole('switch')).not.toBeInTheDocument()
        expect(
          screen.queryByRole('button', { name: 'Enable' }),
        ).not.toBeInTheDocument()
      })
    })
  })
})
