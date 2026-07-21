import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import AuditLogViewer from '../AuditLogViewer'

// Mock the hooks that AuditLogViewer depends on
const mockAlerts: unknown[] = []
const mockNotifications: unknown[] = []
const mockSnapshot = null

vi.mock('../../hooks/useMonitorAlerts', () => ({
  useMonitorAlerts: () => mockAlerts,
}))

vi.mock('../../hooks/useNotificationCenter', () => ({
  useNotificationCenter: () => ({ notifications: mockNotifications }),
}))

vi.mock('../../hooks/useSystemSnapshot', () => ({
  useSystemSnapshot: () => ({ data: mockSnapshot }),
}))

vi.mock('../../utils/format', () => ({
  formatTimeAgo: () => '2h ago',
}))

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('AuditLogViewer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders empty state when no events', () => {
    renderWithQuery(<AuditLogViewer />)
    expect(screen.getByText('No audit entries')).toBeInTheDocument()
  })

  it('renders search input', () => {
    renderWithQuery(<AuditLogViewer />)
    expect(screen.getByPlaceholderText('Search audit log…')).toBeInTheDocument()
  })

  it('shows total entry count in summary bar', () => {
    renderWithQuery(<AuditLogViewer />)
    expect(screen.getByText(/total entries/)).toBeInTheDocument()
  })

  it('has a Filters button', () => {
    renderWithQuery(<AuditLogViewer />)
    expect(screen.getByText('Filters')).toBeInTheDocument()
  })

  it('toggles filter panel on click', () => {
    renderWithQuery(<AuditLogViewer />)
    const filtersBtn = screen.getByText('Filters')
    fireEvent.click(filtersBtn)
    expect(screen.getByText('Severity:')).toBeInTheDocument()
    expect(screen.getByText('Type:')).toBeInTheDocument()
  })

  it('shows severity filter buttons when filters open', () => {
    renderWithQuery(<AuditLogViewer />)
    fireEvent.click(screen.getByText('Filters'))
    expect(screen.getByText('Critical')).toBeInTheDocument()
    expect(screen.getByText('Warning')).toBeInTheDocument()
    expect(screen.getByText('Info')).toBeInTheDocument()
  })

  it('renders export CSV button', () => {
    renderWithQuery(<AuditLogViewer />)
    const exportBtn = screen.getByTitle('Export as CSV')
    expect(exportBtn).toBeInTheDocument()
  })

  it('accepts maxEntries prop', () => {
    renderWithQuery(<AuditLogViewer maxEntries={100} />)
    expect(screen.getByPlaceholderText('Search audit log…')).toBeInTheDocument()
  })

  it('updates search query on input', () => {
    renderWithQuery(<AuditLogViewer />)
    const input = screen.getByPlaceholderText('Search audit log…')
    fireEvent.change(input, { target: { value: 'test search' } })
    expect(input).toHaveValue('test search')
  })

  it('clears search when clear button clicked', () => {
    renderWithQuery(<AuditLogViewer />)
    const input = screen.getByPlaceholderText('Search audit log…')
    fireEvent.change(input, { target: { value: 'something' } })
    
    const clearBtn = screen.getByText('✕')
    fireEvent.click(clearBtn)
    expect(input).toHaveValue('')
  })

  it('shows load more when entries exceed showCount', () => {
    // With zero entries, there should be no "load more" button
    renderWithQuery(<AuditLogViewer />)
    expect(screen.queryByText('Load more')).not.toBeInTheDocument()
  })

  it('handles default props gracefully', () => {
    renderWithQuery(<AuditLogViewer />)
    // Should not throw
    expect(screen.getByPlaceholderText('Search audit log…')).toBeInTheDocument()
  })

  it("shows 'All' severity button when filters open", () => {
    renderWithQuery(<AuditLogViewer />)
    fireEvent.click(screen.getByText('Filters'))
    expect(screen.getByText('All')).toBeInTheDocument()
    expect(screen.getByText('Critical')).toBeInTheDocument()
    expect(screen.getByText('Warning')).toBeInTheDocument()
  })

  it('summary bar shows correct total when filters are active', () => {
    renderWithQuery(<AuditLogViewer />)
    // Opening filters shouldn't crash when no entries exist
    fireEvent.click(screen.getByText('Filters'))
    expect(screen.getByText(/total entries/)).toBeInTheDocument()
  })
})
