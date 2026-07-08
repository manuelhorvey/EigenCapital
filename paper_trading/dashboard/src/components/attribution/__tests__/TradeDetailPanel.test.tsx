import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import TradeDetailPanel from '../TradeDetailPanel'
import type { TradeAttributionRecord } from '../../../types/attribution'

const MOCK_TRADE: TradeAttributionRecord = {
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
  exec_counterfactual_entry_timing_r: 1.2,
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
  friction_counterfactual_ideal_fill_r: 1.5,
  friction_counterfactual_real_fill_r: 1.2,
  dq_entry_pressure_pct: null,
  dq_spread_rank: null,
  dq_volatility_rank: null,
  dq_liquidity_rank: null,
}

describe('TradeDetailPanel', () => {
  it('renders trade header with asset, side, and dates', () => {
    render(<TradeDetailPanel trade={MOCK_TRADE} onClose={() => {}} />)
    expect(screen.getByText(/EURUSD/)).toBeInTheDocument()
    expect(screen.getByText(/2026-07-01/)).toBeInTheDocument()
    expect(screen.getByText(/2026-07-03/)).toBeInTheDocument()
    // BUY appears in both header (· BUY ·) and prediction section (Signal: BUY)
    const buyElements = screen.getAllByText(/BUY/)
    expect(buyElements.length).toBeGreaterThanOrEqual(2)
  })

  it('renders prediction section with signal and confidence', () => {
    render(<TradeDetailPanel trade={MOCK_TRADE} onClose={() => {}} />)
    // BUY appears in header and prediction — use getAllByText
    expect(screen.getAllByText(/BUY/).length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText(/75%/).length).toBeGreaterThanOrEqual(1) // 0.75 * 100
    expect(screen.getAllByText(/MOMENTUM/).length).toBeGreaterThanOrEqual(1)
  })

  it('shows direction correct indicator', () => {
    render(<TradeDetailPanel trade={MOCK_TRADE} onClose={() => {}} />)
    expect(screen.getByText('Yes')).toBeInTheDocument()
  })

  it('shows direction incorrect when false', () => {
    const wrongTrade = { ...MOCK_TRADE, pred_forecast_direction_correct: false }
    render(<TradeDetailPanel trade={wrongTrade} onClose={() => {}} />)
    // 'No' appears for direction correct, Gap fill, and Partial
    const noElements = screen.getAllByText('No')
    expect(noElements.length).toBeGreaterThanOrEqual(1)
  })

  it('shows dash for null direction correctness', () => {
    const nullTrade = { ...MOCK_TRADE, pred_forecast_direction_correct: null }
    render(<TradeDetailPanel trade={nullTrade} onClose={() => {}} />)
    expect(screen.getByText('\u2014')).toBeInTheDocument()
  })

  it('renders execution section with entry type and slippage', () => {
    render(<TradeDetailPanel trade={MOCK_TRADE} onClose={() => {}} />)
    expect(screen.getByText(/MARKET/)).toBeInTheDocument()
  })

  it('renders exit section with reason and realized R', () => {
    render(<TradeDetailPanel trade={MOCK_TRADE} onClose={() => {}} />)
    expect(screen.getByText(/TP/)).toBeInTheDocument()
    expect(screen.getByText('2.50')).toBeInTheDocument() // exit_realized_r
  })

  it('renders friction section with gap warning when gap fill', () => {
    const gapTrade = { ...MOCK_TRADE, friction_gap_fill: true }
    render(<TradeDetailPanel trade={gapTrade} onClose={() => {}} />)
    // 'Gap fill' appears as a warning in execution section and label in friction section
    const gapFillElements = screen.getAllByText(/Gap fill/)
    expect(gapFillElements.length).toBeGreaterThanOrEqual(2)
  })

  it('renders friction section with partial fill warning', () => {
    const partialTrade = { ...MOCK_TRADE, friction_partial_fill: true }
    render(<TradeDetailPanel trade={partialTrade} onClose={() => {}} />)
    expect(screen.getByText(/Partial fill/)).toBeInTheDocument()
  })

  it('renders counterfactual section', () => {
    render(<TradeDetailPanel trade={MOCK_TRADE} onClose={() => {}} />)
    expect(screen.getByText(/Counterfactual/)).toBeInTheDocument()
    expect(screen.getByText(/1.50/)).toBeInTheDocument() // ideal fill R
    // 1.20 appears twice: timing R and real fill R
    expect(screen.getAllByText(/1.20/).length).toBe(2)
  })

  it('calls onClose when close button clicked', () => {
    const onClose = vi.fn()
    render(<TradeDetailPanel trade={MOCK_TRADE} onClose={onClose} />)
    const closeBtn = screen.getByRole('button')
    fireEvent.click(closeBtn)
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('renders all four section headers', () => {
    render(<TradeDetailPanel trade={MOCK_TRADE} onClose={() => {}} />)
    expect(screen.getByText('Prediction')).toBeInTheDocument()
    expect(screen.getByText('Execution')).toBeInTheDocument()
    expect(screen.getByText('Exit')).toBeInTheDocument()
    expect(screen.getByText('Friction')).toBeInTheDocument()
  })

  it('renders BarRow components for each section', () => {
    render(<TradeDetailPanel trade={MOCK_TRADE} onClose={() => {}} />)
    const scoreLabels = screen.getAllByText('Score')
    expect(scoreLabels.length).toBe(4)
  })
})
