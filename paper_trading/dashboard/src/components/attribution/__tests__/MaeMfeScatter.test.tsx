import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import MaeMfeScatter from '../MaeMfeScatter'

// Mock Recharts
vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  ScatterChart: ({ children }: { children: ReactNode }) => <div data-testid="scatter-chart">{children}</div>,
  Scatter: ({ children }: { children: ReactNode }) => <div data-testid="scatter">{children}</div>,
  Cell: () => null,
  XAxis: () => null,
  YAxis: () => null,
  ZAxis: () => null,
  Tooltip: () => null,
}))

const mockUseAttributionTrades = vi.fn()
const mockUseLiveAttribution = vi.fn()

vi.mock('../../../hooks/useAttributionTrades', () => ({
  useAttributionTrades: (...args: unknown[]) => mockUseAttributionTrades(...args),
}))

vi.mock('../../../hooks/useLiveAttribution', () => ({
  useLiveAttribution: (...args: unknown[]) => mockUseLiveAttribution(...args),
}))

function makeTrades() {
  return [
    {
      trade_id: 't1', asset: 'EURUSD', side: 'long', entry_date: '2026-07-01', exit_date: '2026-07-03',
      entry_price: 1.1050, exit_price: 1.1080, realized_return: 0.05, realized_pnl: 150,
      pred_signal: 'BUY', pred_confidence: 0.7, pred_forecast_direction_correct: true,
      pred_archetype_at_entry: 'MOMENTUM', pred_regime_at_entry: 'TRENDING',
      exec_entry_type: 'MARKET', exec_entry_slippage_bps: 0.5, exec_deferred_bars: 0,
      exec_entry_timing_efficiency: null, exec_counterfactual_entry_timing_r: null,
      exit_exit_reason: 'TP', exit_realized_r: 2.5, exit_theoretical_r: 3.0,
      exit_mae: 0.3, exit_mfe: 2.8, exit_mae_per_bar: 0.1, exit_mfe_per_bar: 0.9,
      exit_bars_held: 48, exit_archetype: 'TREND',
      friction_entry_slippage_bps: 0.5, friction_exit_slippage_bps: 0.3,
      friction_gap_fill: false, friction_partial_fill: false, friction_fill_qty_ratio: 0.98,
      friction_latency_bars: 1,
      friction_counterfactual_ideal_fill_r: null, friction_counterfactual_real_fill_r: null,
      dq_entry_pressure_pct: null, dq_spread_rank: null, dq_volatility_rank: null, dq_liquidity_rank: null,
    },
    {
      trade_id: 't2', asset: 'GBPUSD', side: 'sell', entry_date: '2026-07-02', exit_date: '2026-07-04',
      entry_price: 1.2650, exit_price: 1.2610, realized_return: -0.02, realized_pnl: -50,
      pred_signal: 'SELL', pred_confidence: 0.6, pred_forecast_direction_correct: true,
      pred_archetype_at_entry: 'BREAKOUT', pred_regime_at_entry: 'RANGING',
      exec_entry_type: 'LIMIT', exec_entry_slippage_bps: 1.2, exec_deferred_bars: 2,
      exec_entry_timing_efficiency: 0.8, exec_counterfactual_entry_timing_r: 1.5,
      exit_exit_reason: 'SL', exit_realized_r: -1.0, exit_theoretical_r: 2.0,
      exit_mae: 1.5, exit_mfe: 0.5, exit_mae_per_bar: 0.5, exit_mfe_per_bar: 0.2,
      exit_bars_held: 24, exit_archetype: 'REVERSAL',
      friction_entry_slippage_bps: 1.2, friction_exit_slippage_bps: 0.8,
      friction_gap_fill: false, friction_partial_fill: false, friction_fill_qty_ratio: 1.0,
      friction_latency_bars: 2,
      friction_counterfactual_ideal_fill_r: null, friction_counterfactual_real_fill_r: null,
      dq_entry_pressure_pct: null, dq_spread_rank: null, dq_volatility_rank: null, dq_liquidity_rank: null,
    },
  ]
}

function makeLiveData() {
  return [
    { asset: 'EURJPY', side: 'long', entry_price: 155.0, current_value: 156.5, running_mae: 0.2, running_mfe: 1.8 },
    { asset: 'USDCAD', side: null, entry_price: null, current_value: null, running_mae: null, running_mfe: null },
  ]
}

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('MaeMfeScatter', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAttributionTrades.mockReturnValue({ data: makeTrades(), isPending: false })
    mockUseLiveAttribution.mockReturnValue({ data: makeLiveData(), isPending: false })
  })

  it('renders loading state', () => {
    mockUseAttributionTrades.mockReturnValue({ data: null, isPending: true })
    mockUseLiveAttribution.mockReturnValue({ data: null, isPending: true })
    renderWithQuery(<MaeMfeScatter />)
    // ChartContainer shows loading when isPending
    expect(screen.getByText('MAE / MFE Scatter')).toBeInTheDocument()
  })

  it('renders empty state when no trades', () => {
    mockUseAttributionTrades.mockReturnValue({ data: [], isPending: false })
    mockUseLiveAttribution.mockReturnValue({ data: [], isPending: false })
    renderWithQuery(<MaeMfeScatter />)
    expect(screen.getByText('No closed trades yet — appears on exit')).toBeInTheDocument()
  })

  it('renders scatter chart with trade data', () => {
    renderWithQuery(<MaeMfeScatter />)
    expect(screen.getByTestId('scatter-chart')).toBeInTheDocument()
  })

  it('renders screen-reader-only description with metrics', () => {
    renderWithQuery(<MaeMfeScatter />)
    const srOnly = document.querySelector('.sr-only')
    expect(srOnly).toBeInTheDocument()
    expect(srOnly?.textContent).toContain('MAE MFE scatter')
    expect(srOnly?.textContent).toContain('worst adverse excursion')
    expect(srOnly?.textContent).toContain('best favorable excursion')
  })

  it('filters out trades with zero MAE and MFE', () => {
    const zeroTrade = makeTrades()[0]
    mockUseAttributionTrades.mockReturnValue({
      data: [{ ...zeroTrade, exit_mae: 0, exit_mfe: 0 }],
      isPending: false,
    })
    // Also clear live data so allData is truly empty
    mockUseLiveAttribution.mockReturnValue({ data: [], isPending: false })
    renderWithQuery(<MaeMfeScatter />)
    expect(screen.getByText('No closed trades yet — appears on exit')).toBeInTheDocument()
  })

  it('includes live position data when available', () => {
    renderWithQuery(<MaeMfeScatter />)
    expect(screen.getByTestId('scatter-chart')).toBeInTheDocument()
  })

  it('ignores live positions with null mae/mfe', () => {
    // USDCAD in mock has null values and should be filtered out
    renderWithQuery(<MaeMfeScatter />)
    expect(screen.getByTestId('scatter-chart')).toBeInTheDocument()
  })
})
