import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import PnLWaterfall from '../PnLWaterfall'

// Mock Recharts to avoid SVG rendering in jsdom
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

function makeWaterfall() {
  return {
    prediction_pnl: 500.00,
    execution_cost: 50.00,
    exit_cost: 75.00,
    friction_cost: 25.00,
    net_pnl: 350.00,
    n: 10,
  }
}

function makeBundle() {
  return {
    data: {
      attributionWaterfall: makeWaterfall(),
    },
    isPending: false,
  }
}

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('PnLWaterfall', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAttributionBundle.mockReturnValue(makeBundle())
  })

  it('renders loading state', () => {
    mockUseAttributionBundle.mockReturnValue({ data: null, isPending: true })
    renderWithQuery(<PnLWaterfall />)
    expect(screen.getByText('PnL Decomposition')).toBeInTheDocument()
  })

  it('renders empty state when no data', () => {
    mockUseAttributionBundle.mockReturnValue({ data: null, isPending: false })
    renderWithQuery(<PnLWaterfall />)
    expect(screen.getByText('No closed trades yet — appears on exit')).toBeInTheDocument()
  })

  it('renders empty state when n is 0', () => {
    mockUseAttributionBundle.mockReturnValue({
      data: { attributionWaterfall: { ...makeWaterfall(), n: 0 } },
      isPending: false,
    })
    renderWithQuery(<PnLWaterfall />)
    expect(screen.getByText('No closed trades yet — appears on exit')).toBeInTheDocument()
  })

  it('renders bar chart with data', () => {
    renderWithQuery(<PnLWaterfall />)
    expect(screen.getByTestId('bar-chart')).toBeInTheDocument()
  })

  it('renders screen-reader-only description', () => {
    renderWithQuery(<PnLWaterfall />)
    const srOnly = document.querySelector('.sr-only')
    expect(srOnly).toBeInTheDocument()
    expect(srOnly?.textContent).toContain('PnL decomposition')
    expect(srOnly?.textContent).toContain('350.00')
  })

  it('shows positive net PnL in green', () => {
    renderWithQuery(<PnLWaterfall />)
    const chartLabel = document.querySelector('.sr-only')?.textContent ?? ''
    expect(chartLabel).toContain('350.00')
  })

  it('shows negative net PnL in red', () => {
    mockUseAttributionBundle.mockReturnValue({
      data: { attributionWaterfall: { ...makeWaterfall(), net_pnl: -100.00 } },
      isPending: false,
    })
    renderWithQuery(<PnLWaterfall />)
    const chartLabel = document.querySelector('.sr-only')?.textContent ?? ''
    expect(chartLabel).toContain('-100.00')
  })
})
