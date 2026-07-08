import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import SlippageHistogram from '../SlippageHistogram'

// Mock Recharts
vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  BarChart: ({ children }: { children: ReactNode }) => <div data-testid="bar-chart">{children}</div>,
  Bar: () => <div data-testid="bar" />,
  Cell: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
}))

const mockUseAttributionBundle = vi.fn()

vi.mock('../../../hooks/useAttributionBundle', () => ({
  useAttributionBundle: (...args: unknown[]) => mockUseAttributionBundle(...args),
}))

function makeSlippageData() {
  return {
    entry_slippage: [0.5, 1.2, 0.3, 2.1, 0.8, 3.0, 0.1, 1.5, 0.6, 4.0],
    exit_slippage: [0.3, 0.8, 0.1, 1.5, 0.6, 2.0, 0.2, 1.0, 0.4, 3.5],
    gap_count: 0,
    partial_fill_count: 1,
    n: 10,
  }
}

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('SlippageHistogram', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAttributionBundle.mockReturnValue({
      data: { executionSlippage: makeSlippageData() },
      isPending: false,
    })
  })

  it('renders loading state', () => {
    mockUseAttributionBundle.mockReturnValue({ data: null, isPending: true })
    renderWithQuery(<SlippageHistogram />)
    expect(screen.getByText('Slippage Distribution (bps)')).toBeInTheDocument()
  })

  it('renders empty state when no data', () => {
    mockUseAttributionBundle.mockReturnValue({ data: null, isPending: false })
    renderWithQuery(<SlippageHistogram />)
    expect(screen.getByText(/No closed trades yet/)).toBeInTheDocument()
  })

  it('renders empty state when n is 0', () => {
    mockUseAttributionBundle.mockReturnValue({
      data: { executionSlippage: { entry_slippage: [], exit_slippage: [], gap_count: 0, partial_fill_count: 0, n: 0 } },
      isPending: false,
    })
    renderWithQuery(<SlippageHistogram />)
    expect(screen.getByText(/No closed trades yet/)).toBeInTheDocument()
  })

  it('renders entry and exit slippage sections', () => {
    renderWithQuery(<SlippageHistogram />)
    expect(screen.getByText('Entry Slippage')).toBeInTheDocument()
    expect(screen.getByText('Exit Slippage')).toBeInTheDocument()
  })

  it('renders bar charts', () => {
    renderWithQuery(<SlippageHistogram />)
    const charts = screen.getAllByTestId('bar-chart')
    expect(charts.length).toBe(2)
  })

  it('renders screen-reader-only description', () => {
    renderWithQuery(<SlippageHistogram />)
    const srOnly = document.querySelector('.sr-only')
    expect(srOnly).toBeInTheDocument()
    expect(srOnly?.textContent).toContain('Slippage distribution')
  })

  it('calculates and reports average entry slippage', () => {
    renderWithQuery(<SlippageHistogram />)
    const srOnly = document.querySelector('.sr-only')
    // avg entry: (0.5+1.2+0.3+2.1+0.8+3.0+0.1+1.5+0.6+4.0)/10 = 14.1/10 = 1.41
    // Component formats with toFixed(1) → '1.4'
    expect(srOnly?.textContent).toContain('1.4')
  })

  it('calculates and reports average exit slippage', () => {
    renderWithQuery(<SlippageHistogram />)
    const srOnly = document.querySelector('.sr-only')
    // avg exit: (0.3+0.8+0.1+1.5+0.6+2.0+0.2+1.0+0.4+3.5)/10 = 10.4/10 = 1.04
    // Component formats with toFixed(1) → '1.0'
    expect(srOnly?.textContent).toContain('1.0')
  })
})
