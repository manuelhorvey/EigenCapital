import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useTradeInspector } from '../useTradeInspector'
import type { TradeAttributionRecord } from '../../types/attribution'

// ── Mocks ─────────────────────────────────────────────────────────

const mockAttributionTrades: TradeAttributionRecord[] = [
  {
    trade_id: 't1',
    asset: 'EURUSD',
    entry_date: '2026-07-01',
    exit_date: '2026-07-03',
    side: 'buy',
    entry_price: 1.1050,
    exit_price: 1.1080,
    realized_return: 0.0027,
    realized_pnl: 27.0,
    pred_signal: 'BUY',
    pred_confidence: 0.72,
    pred_forecast_direction_correct: true,
    pred_archetype_at_entry: 'MOMENTUM',
    pred_regime_at_entry: 'TRENDING',
    exec_entry_type: 'market',
    exec_entry_slippage_bps: 0.5,
    exec_deferred_bars: 0,
    exec_entry_timing_efficiency: 0.9,
    exec_counterfactual_entry_timing_r: 0.1,
    exit_exit_reason: 'TP',
    exit_realized_r: 1.5,
    exit_theoretical_r: 1.6,
    exit_mae: 0.3,
    exit_mfe: 1.8,
    exit_mae_per_bar: 0.1,
    exit_mfe_per_bar: 0.6,
    exit_bars_held: 3,
    exit_archetype: 'MOMENTUM',
    friction_entry_slippage_bps: 0.5,
    friction_exit_slippage_bps: 0.3,
    friction_gap_fill: false,
    friction_partial_fill: false,
    friction_fill_qty_ratio: 1.0,
    friction_latency_bars: 0,
    friction_counterfactual_ideal_fill_r: null,
    friction_counterfactual_real_fill_r: null,
    dq_entry_pressure_pct: null,
    dq_spread_rank: null,
    dq_volatility_rank: null,
    dq_liquidity_rank: null,
  },
  {
    trade_id: 't2',
    asset: 'GBPUSD',
    entry_date: '2026-07-02',
    exit_date: '2026-07-04',
    side: 'sell',
    entry_price: 1.2650,
    exit_price: 1.2610,
    realized_return: 0.0032,
    realized_pnl: 32.0,
    pred_signal: 'SELL',
    pred_confidence: 0.68,
    pred_forecast_direction_correct: true,
    pred_archetype_at_entry: 'BREAKOUT',
    pred_regime_at_entry: 'RANGING',
    exec_entry_type: 'limit',
    exec_entry_slippage_bps: 0.2,
    exec_deferred_bars: 1,
    exec_entry_timing_efficiency: 0.85,
    exec_counterfactual_entry_timing_r: 0.05,
    exit_exit_reason: 'SL',
    exit_realized_r: -0.8,
    exit_theoretical_r: -0.7,
    exit_mae: 0.5,
    exit_mfe: 0.1,
    exit_mae_per_bar: 0.25,
    exit_mfe_per_bar: 0.05,
    exit_bars_held: 2,
    exit_archetype: 'BREAKOUT',
    friction_entry_slippage_bps: 0.2,
    friction_exit_slippage_bps: 0.4,
    friction_gap_fill: false,
    friction_partial_fill: false,
    friction_fill_qty_ratio: 1.0,
    friction_latency_bars: 0,
    friction_counterfactual_ideal_fill_r: null,
    friction_counterfactual_real_fill_r: null,
    dq_entry_pressure_pct: null,
    dq_spread_rank: null,
    dq_volatility_rank: null,
    dq_liquidity_rank: null,
  },
]

let mockData: TradeAttributionRecord[] | undefined = mockAttributionTrades

vi.mock('../useAttributionTrades', () => ({
  useAttributionTrades: vi.fn(() => ({
    data: mockData,
    isPending: false,
    isError: false,
    error: null,
  })),
}))

// ── Tests ──────────────────────────────────────────────────────────

describe('useTradeInspector', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockData = mockAttributionTrades
  })

  it('returns null when no asset is provided', () => {
    const { result } = renderHook(() => useTradeInspector(undefined))
    expect(result.current).toBeNull()
  })

  it('returns null when no trades match the asset', () => {
    const { result } = renderHook(() => useTradeInspector('NONEXISTENT'))
    expect(result.current).toBeNull()
  })

  it('returns null when trades data is undefined', () => {
    mockData = undefined
    const { result } = renderHook(() => useTradeInspector('EURUSD'))
    expect(result.current).toBeNull()
  })

  it('returns null when trades data is empty array', () => {
    mockData = []
    const { result } = renderHook(() => useTradeInspector('EURUSD'))
    expect(result.current).toBeNull()
  })

  it('matches a trade by asset name only', () => {
    const { result } = renderHook(() => useTradeInspector('EURUSD'))
    expect(result.current).not.toBeNull()
    expect(result.current!.basic.asset).toBe('EURUSD')
    expect(result.current!.basic.side).toBe('buy')
  })

  it('matches a trade by asset and entry date', () => {
    const { result } = renderHook(() =>
      useTradeInspector('GBPUSD', '2026-07-02'),
    )
    expect(result.current).not.toBeNull()
    expect(result.current!.basic.asset).toBe('GBPUSD')
    expect(result.current!.basic.entry_date).toBe('2026-07-02')
  })

  it('matches a trade by asset, entry date, and exit date', () => {
    const { result } = renderHook(() =>
      useTradeInspector('EURUSD', '2026-07-01', '2026-07-03'),
    )
    expect(result.current).not.toBeNull()
    expect(result.current!.basic.asset).toBe('EURUSD')
  })

  it('returns null when entry date does not match', () => {
    const { result } = renderHook(() =>
      useTradeInspector('EURUSD', '2099-01-01'),
    )
    expect(result.current).toBeNull()
  })

  it('returns correct basic shape with all required fields', () => {
    const { result } = renderHook(() => useTradeInspector('EURUSD'))
    const basic = result.current!.basic
    expect(basic).toHaveProperty('asset', 'EURUSD')
    expect(basic).toHaveProperty('side', 'buy')
    expect(basic).toHaveProperty('entry_date', '2026-07-01')
    expect(basic).toHaveProperty('exit_date', '2026-07-03')
    expect(basic).toHaveProperty('entry_price', 1.1050)
    expect(basic).toHaveProperty('exit_price', 1.1080)
    expect(basic).toHaveProperty('realized_r', 1.5)
    expect(basic).toHaveProperty('realized_pnl', 27.0)
  })

  it('includes the full attribution record', () => {
    const { result } = renderHook(() => useTradeInspector('GBPUSD'))
    expect(result.current!.attribution).not.toBeNull()
    expect(result.current!.attribution!.trade_id).toBe('t2')
    expect(result.current!.attribution!.pred_archetype_at_entry).toBe('BREAKOUT')
    expect(result.current!.attribution!.exit_exit_reason).toBe('SL')
  })

  it('memoizes result when deps are stable', () => {
    const { result, rerender } = renderHook(() => useTradeInspector('EURUSD'))
    const first = result.current
    rerender()
    expect(result.current).toBe(first)
  })

  it('recomputes when asset changes', () => {
    const { result, rerender } = renderHook(
      ({ asset }) => useTradeInspector(asset),
      { initialProps: { asset: 'EURUSD' } },
    )
    const first = result.current
    expect(first!.basic.asset).toBe('EURUSD')

    rerender({ asset: 'GBPUSD' })
    const second = result.current
    expect(second!.basic.asset).toBe('GBPUSD')
    expect(first).not.toBe(second)
  })

  it('recomputes when entryDate changes', () => {
    const { result, rerender } = renderHook(
      ({ date }) => useTradeInspector('EURUSD', date),
      { initialProps: { date: '2026-07-01' } },
    )
    expect(result.current).not.toBeNull()

    rerender({ date: '2099-01-01' })
    expect(result.current).toBeNull()
  })
})
