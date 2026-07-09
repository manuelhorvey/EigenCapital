import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import PageTransition from '../PageTransition'

describe('PageTransition', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders children initially as opacity-0 then transitions to visible', () => {
    render(
      <PageTransition locationKey="/dashboard" durationMs={200}>
        <div>Content</div>
      </PageTransition>,
    )

    // Initial state: 'enter' → opacity-0
    const container = screen.getByText('Content').parentElement
    expect(container).toHaveClass('opacity-0')

    // After durationMs, should be 'visible' → opacity-100
    act(() => { vi.advanceTimersByTime(200) })
    expect(container).toHaveClass('opacity-100')
  })

  it('fades out then in when locationKey changes', () => {
    const { rerender } = render(
      <PageTransition locationKey="/dashboard" durationMs={100}>
        <div>Dashboard</div>
      </PageTransition>,
    )

    // Initial mount: enter → visible after duration
    act(() => { vi.advanceTimersByTime(100) })

    const container = screen.getByText('Dashboard').parentElement
    expect(container).toHaveClass('opacity-100')

    // Rerender with new locationKey → exit phase
    rerender(
      <PageTransition locationKey="/risk" durationMs={100}>
        <div>Risk</div>
      </PageTransition>,
    )

    // Immediately goes to exit → opacity-0
    // container is the PageTransition wrapper (inner div's parentElement)
    expect(container).toHaveClass('opacity-0')

    // After exit duration → goes to enter (still opacity-0)
    act(() => { vi.advanceTimersByTime(100) })
    // Then after enter duration → visible (opacity-100)
    act(() => { vi.advanceTimersByTime(100) })
    // The container re-rendered with new children
    expect(screen.getByText('Risk').parentElement).toHaveClass('opacity-100')
  })

  it('sets aria-hidden during exit phase', () => {
    const { rerender } = render(
      <PageTransition locationKey="/dashboard" durationMs={100}>
        <div>Content</div>
      </PageTransition>,
    )

    // Wait for initial mount
    act(() => { vi.advanceTimersByTime(100) })

    rerender(
      <PageTransition locationKey="/risk" durationMs={100}>
        <div>New Content</div>
      </PageTransition>,
    )

    // During exit phase, should be aria-hidden
    const wrapper = screen.getByText('New Content').closest('[aria-hidden]')
    expect(wrapper).toHaveAttribute('aria-hidden', 'true')
  })

  it('applies inline transition duration style', () => {
    render(
      <PageTransition locationKey="/test" durationMs={300}>
        <div>Content</div>
      </PageTransition>,
    )

    const wrapper = screen.getByText('Content').parentElement
    expect(wrapper?.style.transitionDuration).toBe('300ms')
  })

  it('applies custom className', () => {
    render(
      <PageTransition locationKey="/test" className="custom-page">
        <div>Content</div>
      </PageTransition>,
    )

    const wrapper = screen.getByText('Content').parentElement
    expect(wrapper).toHaveClass('custom-page')
  })

  it('cleans up timers on unmount', () => {
    const { unmount } = render(
      <PageTransition locationKey="/test" durationMs={500}>
        <div>Content</div>
      </PageTransition>,
    )

    // Unmount before the timer fires
    unmount()

    // Should not throw — timer cleanup succeeded
    act(() => { vi.advanceTimersByTime(500) })
  })

  it('handles rapid locationKey changes', () => {
    const { rerender } = render(
      <PageTransition locationKey="/a" durationMs={100}>
        <div>Page A</div>
      </PageTransition>,
    )

    // Wait for initial mount
    act(() => { vi.advanceTimersByTime(100) })

    // Rapidly change locationKey twice
    rerender(
      <PageTransition locationKey="/b" durationMs={100}>
        <div>Page B</div>
      </PageTransition>,
    )

    rerender(
      <PageTransition locationKey="/c" durationMs={100}>
        <div>Page C</div>
      </PageTransition>,
    )

    // Should eventually settle on Page C
    act(() => { vi.advanceTimersByTime(300) })
    expect(screen.getByText('Page C').parentElement).toHaveClass('opacity-100')
  })

  it('uses default durationMs when not specified', () => {
    render(
      <PageTransition locationKey="/test">
        <div>Content</div>
      </PageTransition>,
    )

    const wrapper = screen.getByText('Content').parentElement
    expect(wrapper?.style.transitionDuration).toBe('200ms')
  })
})
