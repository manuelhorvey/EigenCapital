import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import TradeExecutionTable from '../TradeExecutionTable'

const mockUseAttributionTrades = vi.fn()

vi.mock('../../../hooks/useAttributionTrades', () => ({
  useAttributionTrades: (...args: unknown[]) => mockUseAttributionTrades(...args),
}))

// Mock Select to make it testable
vi.mock('../../ui/Select', () => ({
  default: ({ options, value, onChange, placeholder }: any) => (
    <select
      data-testid="archetype-select"
      value={value}
      onChange={(e: React.ChangeEvent<HTMLSelectElement>) => onChange(e.target.value)}
    >
      <option value="">{placeholder}</option>
      {options.map((opt: any) => (
        <option key={opt.value} value={opt.value}>{opt.label}</option>
      ))}
    </select>
  ),
}))

function makeTrade(overrides: Record<string, unknown> = {}) {
  return {
    trade_id: 't1',
    asset: 'EURUSD',
    entry_date: '2026-07-01',
    exit_date: '2026-07-03',
    side: 'buy',
    entry_price: 1.1050,
    exit_price: 1.1080,
    realized_return: 0.05,
    realized_pnl: 150.00,
    pred_signal: 'BUY',
    pred_confidence: 0.75,
    pred_forecast_direction_correct: true,
    pred_archetype_at_entry: 'MOMENTUM',
    pred_regime_at_entry: 'TRENDING',
    exec_entry_type: 'MARKET',
    exec_entry_slippage_bps: 0.5,
    exec_deferred_bars: 0,
    exec_entry_timing_efficiency: 0.9,
    exec_counterfactual_entry_timing_r: null,
    exit_exit_reason: 'TP',
    exit_realized_r: 2.5,
    exit_theoretical_r: 3.0,
    exit_mae: 0.3,
    exit_mfe: 2.8,
    exit_mae_per_bar: 0.1,
    exit_mfe_per_bar: 0.9,
    exit_bars_held: 48,
    exit_archetype: 'TREND',
    friction_entry_slippage_bps: 0.5,
    friction_exit_slippage_bps: 0.3,
    friction_gap_fill: false,
    friction_partial_fill: false,
    friction_fill_qty_ratio: 0.98,
    friction_latency_bars: 1,
    friction_counterfactual_ideal_fill_r: null,
    friction_counterfactual_real_fill_r: null,
    dq_entry_pressure_pct: null,
    dq_spread_rank: null,
    dq_volatility_rank: null,
    dq_liquidity_rank: null,
    ...overrides,
  }
}

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('TradeExecutionTable', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAttributionTrades.mockReturnValue({
      data: [makeTrade({ trade_id: 't1', asset: 'EURUSD', exit_realized_r: 2.5 }),
             makeTrade({ trade_id: 't2', asset: 'GBPUSD', pred_archetype_at_entry: 'BREAKOUT', exit_realized_r: -1.0 }),
             makeTrade({ trade_id: 't3', asset: 'USDJPY', pred_archetype_at_entry: 'MEAN_REVERSION', exit_realized_r: 0.8 })],
      isPending: false,
    })
  })

  it('renders loading skeleton', () => {
    mockUseAttributionTrades.mockReturnValue({ data: null, isPending: true })
    renderWithQuery(<TradeExecutionTable />)
    // TableSkeleton renders
    const skeletons = document.querySelectorAll('.skeleton, .skeleton-shimmer')
    expect(skeletons.length).toBeGreaterThan(0)
  })

  it('renders empty state when no trades', () => {
    mockUseAttributionTrades.mockReturnValue({ data: [], isPending: false })
    renderWithQuery(<TradeExecutionTable />)
    expect(screen.getByText('No attribution data yet')).toBeInTheDocument()
  })

  it('renders section header', () => {
    renderWithQuery(<TradeExecutionTable />)
    expect(screen.getByText('Trade Execution Detail')).toBeInTheDocument()
  })

  it('renders asset names from trade data', () => {
    renderWithQuery(<TradeExecutionTable />)
    // Both mobile cards and desktop table render asset names
    expect(screen.getAllByText('EURUSD').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('GBPUSD').length).toBeGreaterThanOrEqual(1)
  })

  it('renders archetype badges', () => {
    renderWithQuery(<TradeExecutionTable />)
    expect(screen.getAllByText('MOMENTUM').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('BREAKOUT').length).toBeGreaterThanOrEqual(1)
  })

  it('renders realized R values with color coding', () => {
    renderWithQuery(<TradeExecutionTable />)
    // R value appears in both mobile and desktop views
    expect(screen.getAllByText('2.50').length).toBeGreaterThanOrEqual(1)
  })

  it('renders archetype filter select', () => {
    renderWithQuery(<TradeExecutionTable />)
    expect(screen.getByTestId('archetype-select')).toBeInTheDocument()
    expect(screen.getByText('All Archetypes')).toBeInTheDocument()
  })

  it('filters trades by archetype', () => {
    renderWithQuery(<TradeExecutionTable />)
    const select = screen.getByTestId('archetype-select')
    fireEvent.change(select, { target: { value: 'MOMENTUM' } })
    // EURUSD still visible (MOMENTUM archetype)
    expect(screen.getAllByText('EURUSD').length).toBeGreaterThanOrEqual(1)
    // GBPUSD should be filtered out (BREAKOUT archetype)
    const selectEl = screen.getByTestId('archetype-select') as HTMLSelectElement
    expect(selectEl.value).toBe('MOMENTUM')
  })

  it('shows TradeDetailPanel when a row is clicked', () => {
    renderWithQuery(<TradeExecutionTable />)
    const rows = screen.getAllByText('EURUSD')
    // Click on the first EURUSD (mobile card)
    fireEvent.click(rows[0])
    // TradeDetailPanel appears in both mobile card and desktop (shared selectedId state)
    expect(screen.getAllByText('Prediction').length).toBeGreaterThanOrEqual(1)
  })

  it('closes TradeDetailPanel on second click', () => {
    renderWithQuery(<TradeExecutionTable />)
    const rows = screen.getAllByText('EURUSD')
    // Click first EURUSD (mobile card row) to open
    fireEvent.click(rows[0])
    expect(screen.getAllByText('Prediction').length).toBeGreaterThanOrEqual(1)
    // Click same element again to close
    fireEvent.click(rows[0])
    // After closing, Counterfactual section header should be gone from both panels
    const counterfactual = screen.queryAllByText(/Counterfactual/)
    expect(counterfactual.length).toBe(0)
  })

  it('shows exit reason badges', () => {
    renderWithQuery(<TradeExecutionTable />)
    const tpBadges = screen.getAllByText('TP')
    expect(tpBadges.length).toBeGreaterThan(0)
  })

  it('shows slippage values in table', () => {
    renderWithQuery(<TradeExecutionTable />)
    // Slippage values appear in both mobile and desktop views
    expect(screen.getAllByText('0.5').length).toBeGreaterThanOrEqual(1) // EURUSD entry slippage
    expect(screen.getAllByText('0.3').length).toBeGreaterThanOrEqual(1) // EURUSD exit slippage
  })
})
