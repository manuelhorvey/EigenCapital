import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import PnLDrillDown from '../PnLDrillDown'

// Required by EntranceAnimator which uses IntersectionObserver and useMediaQuery
beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })

  // Mock IntersectionObserver for EntranceAnimator
  class MockIntersectionObserver {
    readonly root: Element | null = null
    readonly rootMargin: string = ''
    readonly thresholds: ReadonlyArray<number> = [0]
    constructor() {}
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords(): IntersectionObserverEntry[] { return [] }
  }
  Object.defineProperty(window, 'IntersectionObserver', {
    writable: true,
    value: MockIntersectionObserver,
  })
})

// Mock Recharts to avoid SVG rendering in jsdom
vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  BarChart: ({ children }: { children: ReactNode }) => <div data-testid="bar-chart">{children}</div>,
  AreaChart: ({ children }: { children: ReactNode }) => <div data-testid="area-chart">{children}</div>,
  Bar: ({ children }: { children: ReactNode }) => <div data-testid="bar">{children}</div>,
  Area: () => <div data-testid="area" />,
  Cell: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  CartesianGrid: () => null,
  ReferenceLine: () => null,
}))

const mockUseAttributionTrades = vi.fn()

vi.mock('../../../hooks/useAttributionTrades', () => ({
  useAttributionTrades: (...args: unknown[]) => mockUseAttributionTrades(...args),
}))

function makeTrades(n = 5) {
  return Array.from({ length: n }, (_, i) => ({
    trade_id: `trade-${i}`,
    asset: i % 2 === 0 ? 'EURUSD' : 'GBPUSD',
    entry_date: `2026-0${(i % 9) + 1}-15`,
    exit_date: `2026-0${(i % 9) + 2}-01`,
    side: i % 2 === 0 ? 'long' : 'short',
    entry_price: 1.05 + i * 0.01,
    exit_price: 1.06 + i * 0.01,
    realized_pnl: i % 2 === 0 ? 100 + i * 10 : -(50 + i * 10),
    realized_return: i % 2 === 0 ? 0.01 : -0.005,
    pred_signal: 'BUY',
    pred_confidence: 0.75,
    pred_forecast_direction_correct: i % 2 === 0,
    pred_archetype_at_entry: 'MOMENTUM',
    pred_regime_at_entry: 'RISK_ON',
    exec_entry_type: 'MARKET',
    exec_entry_slippage_bps: 1.0,
    exec_deferred_bars: 0,
    exec_entry_timing_efficiency: 1.0,
    exec_counterfactual_entry_timing_r: 0.5,
    exit_exit_reason: i % 2 === 0 ? 'TP' : 'SL',
    exit_realized_r: i % 2 === 0 ? 1.5 + i * 0.1 : -0.8 - i * 0.1,
    exit_theoretical_r: 2.0,
    exit_mae: i * 5,
    exit_mfe: i * 10,
    exit_mae_per_bar: 0.5,
    exit_mfe_per_bar: 1.0,
    exit_bars_held: 48,
    exit_archetype: 'MOMENTUM',
    friction_entry_slippage_bps: 0.5,
    friction_exit_slippage_bps: 0.3,
    friction_gap_fill: false,
    friction_partial_fill: false,
    friction_fill_qty_ratio: 1.0,
    friction_latency_bars: 0,
    friction_counterfactual_ideal_fill_r: 0.8,
    friction_counterfactual_real_fill_r: 0.7,
    dq_entry_pressure_pct: 15,
    dq_spread_rank: 2,
    dq_volatility_rank: 3,
    dq_liquidity_rank: 1,
  }))
}

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('PnLDrillDown', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAttributionTrades.mockReturnValue({ data: makeTrades(5), isPending: false })
  })

  it('renders KPI cards with trade data', () => {
    renderWithQuery(<PnLDrillDown />)
    // KPI labels may also appear in sort buttons; use getAllByText to confirm at least one exists
    expect(screen.getAllByText('Total P&L').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Win Rate').length).toBeGreaterThanOrEqual(1)
    // Verify total PnL value is rendered (formatted currency string)
    expect(screen.getAllByText('+$220.00').length).toBeGreaterThanOrEqual(1)
  })

  it('renders empty state when no trades', () => {
    mockUseAttributionTrades.mockReturnValue({ data: [], isPending: false })
    renderWithQuery(<PnLDrillDown />)
    expect(screen.getByText('No closed trades yet')).toBeInTheDocument()
  })

  it('shows per-asset breakdown section with assets', () => {
    renderWithQuery(<PnLDrillDown />)
    expect(screen.getByText('Per-Asset Breakdown')).toBeInTheDocument()
    // Asset names appear in both breakdown table and trade list; check at least one exists
    expect(screen.getAllByText('EURUSD').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('GBPUSD').length).toBeGreaterThanOrEqual(1)
  })

  it('renders time aggregation buttons', () => {
    renderWithQuery(<PnLDrillDown />)
    expect(screen.getByText('Daily')).toBeInTheDocument()
    expect(screen.getByText('Weekly')).toBeInTheDocument()
    expect(screen.getByText('Monthly')).toBeInTheDocument()
  })

  it('switches time aggregation on button click', () => {
    renderWithQuery(<PnLDrillDown />)
    const weeklyButton = screen.getByText('Weekly')
    fireEvent.click(weeklyButton)
    expect(weeklyButton.className).toContain('bg-panel')
  })

  it('renders period P&L chart when data exists', () => {
    renderWithQuery(<PnLDrillDown />)
    // Area chart for cumulative P&L
    expect(screen.getByTestId('area-chart')).toBeInTheDocument()
  })

  it('renders period bar chart when data exists', () => {
    renderWithQuery(<PnLDrillDown />)
    expect(screen.getByTestId('bar-chart')).toBeInTheDocument()
  })

  it('renders cumulative P&L chart with title', () => {
    mockUseAttributionTrades.mockReturnValue({ data: makeTrades(8), isPending: false })
    renderWithQuery(<PnLDrillDown />)
    expect(screen.getByText('P&L Over Time')).toBeInTheDocument()
  })

  it('renders Export button in per-asset breakdown', () => {
    renderWithQuery(<PnLDrillDown />)
    const exportButtons = screen.getAllByText('Export')
    expect(exportButtons.length).toBeGreaterThanOrEqual(1)
  })

  it('shows trade list section with expandable toggle', () => {
    renderWithQuery(<PnLDrillDown />)
    // Trade List text appears in both the expandable header and the inner panel
    expect(screen.getAllByText('Trade List').length).toBeGreaterThanOrEqual(1)
    // The expandable toggle button should exist (may contain 'Trade List' in its aria-label or text)
    const buttons = screen.getAllByRole('button').filter(b => b.textContent?.includes('Trade List'))
    expect(buttons.length).toBeGreaterThanOrEqual(1)
  })

  it('formats PnL values correctly', () => {
    renderWithQuery(<PnLDrillDown />)
    // Multiple PnL values appear (KPI, per-asset rows, trade list).
    // Confirm at least one formatted value exists.
    const pnlValues = screen.getAllByText(/\$[\d.]+/)
    expect(pnlValues.length).toBeGreaterThanOrEqual(1)
  })

  it('displays sortable columns in per-asset table', () => {
    renderWithQuery(<PnLDrillDown />)
    // Sort buttons may duplicate labels that appear in KPI cards; use getAllByText
    expect(screen.getAllByText('Asset').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('P&L').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Trades').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Win %').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Avg R').length).toBeGreaterThanOrEqual(1)
  })

  it('handles loading state gracefully', () => {
    mockUseAttributionTrades.mockReturnValue({ data: undefined, isPending: true })
    renderWithQuery(<PnLDrillDown />)
    // Should not crash - KPI cards will show zero values
    expect(screen.getByText('Total P&L')).toBeInTheDocument()
  })
})
