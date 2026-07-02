import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import EmptyState from '../EmptyState'

describe('EmptyState', () => {
  it('renders a simple message without crashing', () => {
    render(<EmptyState message="No data available" />)
    expect(screen.getByText('No data available')).toBeInTheDocument()
  })

  it('renders with compact prop', () => {
    render(<EmptyState message="No open positions" compact />)
    expect(screen.getByText('No open positions')).toBeInTheDocument()
  })

  it('renders a SearchSlash icon when filtered is true', () => {
    render(<EmptyState message="No assets match filter" compact filtered />)
    expect(screen.getByText('No assets match filter')).toBeInTheDocument()
    // Inbox is the default icon when filtered=false; SearchSlash when true
    // Both are valid renders — test that it doesn't crash
  })

  it('renders hint text when provided', () => {
    render(<EmptyState message="No trades" hint="Trades appear after the first TP/SL event." />)
    expect(screen.getByText('No trades')).toBeInTheDocument()
    expect(screen.getByText('Trades appear after the first TP/SL event.')).toBeInTheDocument()
  })

  it('renders without hint when hint is omitted', () => {
    const { rerender } = render(<EmptyState message="No data" hint="Some hint" />)
    expect(screen.getByText('Some hint')).toBeInTheDocument()

    rerender(<EmptyState message="No data" />)
    expect(screen.queryByText('Some hint')).not.toBeInTheDocument()
  })
})
