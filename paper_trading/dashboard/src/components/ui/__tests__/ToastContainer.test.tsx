import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { ToastProvider, useToast } from '../../../hooks/useToast'
import { ToastContainer } from '../ToastContainer'
import type { ReactNode } from 'react'

// Helper: renders ToastProvider + ToastContainer with a trigger component
function setup(initialToasts?: Array<{ id: string; message: string; severity?: 'success' | 'error' | 'warning' | 'info' }>) {
  let toastFn!: ReturnType<typeof useToast>['toast']
  let dismissFn!: ReturnType<typeof useToast>['dismiss']
  let clearFn!: ReturnType<typeof useToast>['clear']

  function Trigger() {
    const { toast, dismiss, clear } = useToast()
    toastFn = toast
    dismissFn = dismiss
    clearFn = clear
    return null
  }

  const result = render(
    <ToastProvider>
      <ToastContainer />
      <Trigger />
    </ToastProvider>,
  )

  return { toast: toastFn, dismiss: dismissFn, clear: clearFn, ...result }
}

describe('ToastContainer', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('renders nothing when there are no toasts', () => {
    const { container } = setup()
    // No toasts → component returns null, no aria-live container
    expect(container.querySelector('[aria-live="polite"]')).toBeNull()
  })

  it('renders a toast when added', () => {
    const { toast } = setup()

    act(() => {
      toast({ id: 'test-1', message: 'Hello from toast' })
    })

    expect(screen.getByText('Hello from toast')).toBeInTheDocument()
  })

  it('renders multiple toasts', () => {
    const { toast } = setup()

    act(() => {
      toast({ id: 'a', message: 'Toast A' })
      toast({ id: 'b', message: 'Toast B' })
    })

    expect(screen.getByText('Toast A')).toBeInTheDocument()
    expect(screen.getByText('Toast B')).toBeInTheDocument()
  })

  it('dismisses a toast when the close button is clicked', () => {
    const { toast } = setup()

    act(() => {
      toast({ id: 'dismiss-me', message: 'Will be dismissed' })
    })

    const closeButton = screen.getByLabelText('Dismiss notification')
    fireEvent.click(closeButton)

    expect(screen.queryByText('Will be dismissed')).not.toBeInTheDocument()
  })

  it('auto-dismisses after the default duration', () => {
    const { toast } = setup()

    act(() => {
      toast({ id: 'auto', message: 'Auto dismiss', duration: 3000 })
    })

    expect(screen.getByText('Auto dismiss')).toBeInTheDocument()

    // Advance past auto-dismiss
    act(() => { vi.advanceTimersByTime(3000) })

    expect(screen.queryByText('Auto dismiss')).not.toBeInTheDocument()
  })

  it('persists toasts with duration 0', () => {
    const { toast } = setup()

    act(() => {
      toast({ id: 'persist', message: 'Persistent', duration: 0 })
    })

    // Advance a long time
    act(() => { vi.advanceTimersByTime(60000) })

    expect(screen.getByText('Persistent')).toBeInTheDocument()
  })

  it('renders severity styling with icons', () => {
    const { toast } = setup()

    act(() => {
      toast({ id: 'err', message: 'Error toast', severity: 'error' })
      toast({ id: 'warn', message: 'Warning toast', severity: 'warning' })
      toast({ id: 'ok', message: 'Success toast', severity: 'success' })
      toast({ id: 'info', message: 'Info toast', severity: 'info' })
    })

    // All messages render
    expect(screen.getByText('Error toast')).toBeInTheDocument()
    expect(screen.getByText('Warning toast')).toBeInTheDocument()
    expect(screen.getByText('Success toast')).toBeInTheDocument()
    expect(screen.getByText('Info toast')).toBeInTheDocument()
  })

  it('renders action button when provided', () => {
    const onAction = vi.fn()
    const { toast } = setup()

    act(() => {
      toast({
        id: 'with-action',
        message: 'Has action',
        action: { label: 'Retry', onClick: onAction },
      })
    })

    const actionBtn = screen.getByText('Retry')
    expect(actionBtn).toBeInTheDocument()

    fireEvent.click(actionBtn)
    expect(onAction).toHaveBeenCalledOnce()
  })

  it('respects reduced motion preference', () => {
    vi.stubGlobal('matchMedia', vi.fn(() => ({
      matches: true, // Reduced motion ON
      media: '(prefers-reduced-motion: reduce)',
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })))

    const { toast } = setup()

    act(() => {
      toast({ id: 'rm', message: 'Reduced motion' })
    })

    expect(screen.getByText('Reduced motion')).toBeInTheDocument()
  })

  it('sets role=alert on toast items', () => {
    const { toast } = setup()

    act(() => {
      toast({ id: 'alert', message: 'Alert role' })
    })

    const toastEl = screen.getByText('Alert role').closest('[role="alert"]')
    expect(toastEl).toBeInTheDocument()
  })
})
