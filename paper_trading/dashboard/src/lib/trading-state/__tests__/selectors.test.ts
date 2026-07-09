import { describe, it, expect } from 'vitest'
import { toAssetTradingState, toPortfolioTradingState } from '../selectors'
import type { AssetState, Portfolio, EdgeHealthSummary } from '../../../types/portfolio'
import type { AssetTradingState } from '../types'

// ── Helpers ───────────────────────────────────────────────────────────

function makeAssetState(overrides: Partial<AssetState> = {}): AssetState {
  return {
    metrics: {
      asset: 'EURUSD',
      current_value: 100_000,
      settled_value: 100_000,
      mtm_value: 100_000,
      total_return: 0,
      settled_return: 0,
      mtm_return: 0,
      drawdown: 0,
      profit_factor: null,
      win_rate: 0.5,
      n_trades: 0,
      n_signals: 0,
      signal_distribution: { BUY: 0, SELL: 0, FLAT: 0 },
      mean_confidence: 0.5,
      mean_prob_long: 0.5,
      mean_prob_short: 0.5,
      current_price: 1.1234,
      last_signal_date: null,
      monthly_pf: null,
      position: null,
      current_sl_mult: 2,
      current_tp_mult: 2,
      trade_log: [],
      feature_stability: { jaccard_top_10: null, spearman_rank_corr: null, penalty: 0, window_id: null },
      exit_reasons: { tp_rate: 0, sl_rate: 0, breakeven_rate: 0, flip_rate: 0, expiry_rate: 0, avg_r: 0 },
      archetype_stats: {},
      meta_inference: null,
      scale_out_active: false,
      remaining_fraction: 1,
      scale_out_tiers: null,
      psi_drift: { per_feature: [], worst_classification: '', moderate_count: 0, severe_count: 0, psi_ok: true, penalty: 0 },
      sharpe_ratio: null,
      psr_gt_0: null,
      psr_gt_1: null,
      min_trl: null,
      crs: null,
      hhi: null,
    },
    halt: {
      halted: false,
      reasons: [],
      hard_reasons: [],
      soft_warnings: [],
      drawdown_ok: true,
      monthly_pf_ok: true,
      drought_ok: true,
      drift_ok: true,
      narrative_ok: true,
      liquidity_ok: true,
      psi_ok: true,
    },
    validity_state: 'GREEN',
    validity_exposure: 1,
    last_signal: null,
    gate_override: false,
    signal_flip: false,
    final_signal: null,
    execution_state: 'idle',
    sl_mult: 2,
    tp_mult: 2,
    meta_confidence: null,
    meta_decision: null,
    feature_stability_jaccard: null,
    feature_stability_spearman: null,
    sell_only: false,
    tripwire_active: false,
    liquidity_regime: 'NORMAL',
    liquidity_sl_mult: 1,
    liquidity_size_scalar: 1,
    narrative_sl_mult: 1,
    narrative_size_scalar: 1,
    narrative_regime: null,
    narrative_stale: false,
    regime_geometry: {},
    soft_warnings: [],
    stop_out_last_side: null,
    stop_out_last_cycle: null,
    last_regime_long_prob: null,
    last_regime_label: null,
    sizing_chain: null,
    total_exits: 0,
    sl_exits: 0,
    sl_hit_rate: null,
    ...overrides,
  }
}

function makeDefaultPortfolio(): Portfolio {
  return {
    total_value: 100_000,
    mtm_value: 100_000,
    total_return: 2.5,
    realized_value: 100_000,
    realized_return: 1.5,
    unrealized_pnl: 0,
    days_running: 30,
    runtime_hours: 720,
    start_date: '2026-06-07',
    start_datetime: '2026-06-07T00:00:00Z',
    last_update: '2026-07-07T12:00:00Z',
    capital: 100_000,
    allocations: { EURUSD: 0.05 },
    deployment_cleared: true,
    open_positions: 1,
    closed_trades: 10,
    position_concentration: { long: 1, short: 0, total: 1, skew: 1, dominant_side: 'long', threshold: 0.75, alert: false },
  }
}

// ── toAssetTradingState ─────────────────────────────────────────────

describe('toAssetTradingState', () => {
  it('returns CLOSED position state when no position and not halted', () => {
    const result = toAssetTradingState('EURUSD', makeAssetState())
    expect(result.identity).toBe('EURUSD')
    expect(result.position_state).toBe('CLOSED')
    expect(result.direction).toBeNull()
  })

  it('returns OPEN position state when position exists', () => {
    const state = makeAssetState({
      metrics: {
        ...makeAssetState().metrics,
        position: { side: 'long', entry: 1.12, sl: 1.11, tp: 1.14, current_vol: 1000, unrealized_pnl: 50 },
      },
    })
    const result = toAssetTradingState('EURUSD', state)
    expect(result.position_state).toBe('OPEN')
    expect(result.direction).toBe('LONG')
  })

  it('returns HALTED position state when halted flag is true', () => {
    const state = makeAssetState({
      halt: { ...makeAssetState().halt, halted: true, reasons: ['drawdown'] },
    })
    const result = toAssetTradingState('EURUSD', state)
    expect(result.position_state).toBe('HALTED')
  })

  it('sets direction from position side', () => {
    const longState = makeAssetState({
      metrics: { ...makeAssetState().metrics, position: { side: 'long', entry: 1.12, sl: 1.11, tp: 1.14, current_vol: 1000, unrealized_pnl: 50 } },
    })
    expect(toAssetTradingState('EURUSD', longState).direction).toBe('LONG')

    const shortState = makeAssetState({
      metrics: { ...makeAssetState().metrics, position: { side: 'short', entry: 1.12, sl: 1.13, tp: 1.10, current_vol: 1000, unrealized_pnl: -20 } },
    })
    expect(toAssetTradingState('EURUSD', shortState).direction).toBe('SHORT')
  })

  it('sets direction from openPos position when metrics.position is null', () => {
    const state = makeAssetState()
    const result = toAssetTradingState('EURUSD', state, {
      adaptive_exit_phase: 'STATIC',
      peak_mfe_r: null,
      sl_update_count: 0,
      current_value: 100_000,
      position: { side: 'short', entry: 1.12, vol: 1000 },
    })
    expect(result.direction).toBe('SHORT')
  })

  it('computes PnL state from position and exit reasons', () => {
    const state = makeAssetState({
      metrics: {
        ...makeAssetState().metrics,
        position: { side: 'long', entry: 1.12, sl: 1.11, tp: 1.14, current_vol: 1000, unrealized_pnl: 50 },
        exit_reasons: { tp_rate: 0.3, sl_rate: 0.2, breakeven_rate: 0.1, flip_rate: 0.1, expiry_rate: 0.1, avg_r: 0.8 },
      },
    })
    const result = toAssetTradingState('EURUSD', state)
    expect(result.pnl_state.unrealized).toBe(50)
    expect(result.pnl_state.avg_r).toBe(0.8)
  })

  it('computes risk level LOW when drawdown pressure is low', () => {
    const state = makeAssetState({
      metrics: { ...makeAssetState().metrics, drawdown: -0.01, monthly_pf: 0.5 },
    })
    const result = toAssetTradingState('EURUSD', state)
    expect(result.risk_state.level).toBe('LOW')
  })

  it('computes risk level MEDIUM when drawdown pressure is moderate', () => {
    // drawdown_pressure = | -2 | / max(|0.5|, 0.01) = 2/0.5 = 4.0... clamped to 1.0
    // Actually drawdown is -2, monthly_pf is 0.5, so pressure = 2/0.5 = 4 clamped to 1
    // That's > 0.7 so it's HIGH. Let's make drawdown = -0.2 and monthly_pf = 0.5
    // pressure = |-0.2|/0.5 = 0.4 → MEDIUM
    const state = makeAssetState({
      metrics: { ...makeAssetState().metrics, drawdown: -0.2, monthly_pf: 0.5 },
    })
    const result = toAssetTradingState('EURUSD', state)
    expect(result.risk_state.level).toBe('MEDIUM')
  })

  it('computes risk level HIGH when drawdown pressure exceeds 0.7', () => {
    // drawdown_pressure = | -20 | / 0.5 = 40, clamped to 1 → HIGH
    const state = makeAssetState({
      metrics: { ...makeAssetState().metrics, drawdown: -20, monthly_pf: 0.5 },
    })
    const result = toAssetTradingState('EURUSD', state)
    expect(result.risk_state.level).toBe('HIGH')
    expect(result.risk_state.drivers).toContain('drawdown')
  })

  it('includes tripwire driver when tripwire is active', () => {
    const state = makeAssetState({ tripwire_active: true })
    const result = toAssetTradingState('EURUSD', state)
    expect(result.risk_state.drivers).toContain('tripwire')
  })

  it('includes sell_only_filter driver when sell_only is true', () => {
    const state = makeAssetState({ sell_only: true })
    const result = toAssetTradingState('EURUSD', state)
    expect(result.risk_state.drivers).toContain('sell_only_filter')
  })

  it('includes halted driver when halted', () => {
    const state = makeAssetState({
      halt: { ...makeAssetState().halt, halted: true, reasons: ['drawdown'] },
    })
    const result = toAssetTradingState('EURUSD', state)
    expect(result.risk_state.drivers).toContain('halted')
  })

  it('returns STATIC exit phase when no open position', () => {
    const result = toAssetTradingState('EURUSD', makeAssetState())
    expect(result.exit_state.phase).toBe('STATIC')
    expect(result.exit_state.is_active).toBe(false)
  })

  it('sets exit phase from open position data', () => {
    const state = makeAssetState({
      metrics: { ...makeAssetState().metrics, position: { side: 'long', entry: 1.12, sl: 1.11, tp: 1.14, current_vol: 1000, unrealized_pnl: 50 } },
    })
    const result = toAssetTradingState('EURUSD', state, {
      adaptive_exit_phase: 'TRAILING',
      peak_mfe_r: 2.5,
      sl_update_count: 3,
      current_value: 101_000,
    })
    expect(result.exit_state.phase).toBe('TRAILING')
    expect(result.exit_state.is_active).toBe(true)
    expect(result.exit_state.peak_mfe_r).toBe(2.5)
    expect(result.exit_state.sl_is_dynamic).toBe(true)
  })

  it('computes efficiency from peak_mfe_r and r_multiple', () => {
    const state = makeAssetState({
      metrics: { ...makeAssetState().metrics, position: { side: 'long', entry: 100, sl: 99, tp: 102, current_vol: 1000, unrealized_pnl: 175 } },
    })
    // rMultiple = 175 / (100 * 1000) = 0.00175, peakMfeR = 2.5
    // ratio = 0.00175 / 2.5 = 0.0007 → LOW
    const result = toAssetTradingState('EURUSD', state, {
      adaptive_exit_phase: 'TRAILING',
      peak_mfe_r: 2.5,
      sl_update_count: 3,
      current_value: 100_175,
    })
    expect(result.pnl_state.efficiency).toBe('LOW')
  })

  it('computes alpha state with reversal probability from edge health', () => {
    const state = makeAssetState()
    const edgeHealth: EdgeHealthSummary = {
      n_trades: 20,
      n_losers: 5,
      n_reversal_candidates: 1,
      reversal_rate: 0.2,
      warning_threshold: 0.15,
      alert: false,
      mean_mfe_r: null,
      median_mfe_r: null,
    }
    const result = toAssetTradingState('EURUSD', state, null, edgeHealth)
    expect(result.alpha_state.reversal_probability).toBe(0.2)
    expect(result.alpha_state.mfe_capture_quality).toBeNull()
  })

  it('sets flags from drivers plus adaptive exit unconfirmed', () => {
    const state = makeAssetState({
      sell_only: true,
      metrics: { ...makeAssetState().metrics, position: { side: 'short', entry: 1.12, sl: 1.13, tp: 1.10, current_vol: 1000, unrealized_pnl: -10 } },
    })
    const result = toAssetTradingState('EURUSD', state, {
      adaptive_exit_phase: 'BREAKEVEN',
      peak_mfe_r: null,
      sl_update_count: 0,
      current_value: 100_000,
    })
    // The adaptative exit is active (BREAKEVEN !== STATIC) but sl_update_count is 0
    // so ADAPTIVE_EXIT_UNCONFIRMED should be in flags
    expect(result.flags).toContain('sell_only_filter')
    expect(result.flags).toContain('ADAPTIVE_EXIT_UNCONFIRMED')
  })

  it('computes retracement percentage when trailing is active', () => {
    const state = makeAssetState({
      metrics: { ...makeAssetState().metrics, position: { side: 'long', entry: 100, sl: 99, tp: 102, current_vol: 1000, unrealized_pnl: 175 } },
    })
    const result = toAssetTradingState('EURUSD', state, {
      adaptive_exit_phase: 'TRAILING',
      peak_mfe_r: 2.5,
      sl_update_count: 2,
      current_value: 100_175,
      position: { side: 'long', entry: 100, vol: 1000 },
    })
    // entryVal = 100 * 1000 = 100000
    // peakVal = 2.5 * 100000 = 250000
    // currentVal = 100175
    // retracement = 1 - (100175 - 100000) / (250000 - 100000) = 1 - 175/150000 = 1 - 0.00117 = 0.9988
    // clamped to [0,1] → 0.9988
    expect(result.exit_state.retracement_pct).toBeCloseTo(0.9988, 2)
  })
})

// ── toPortfolioTradingState ─────────────────────────────────────────

describe('toPortfolioTradingState', () => {
  it('returns SAFE status with no halted or high-risk assets', () => {
    const result = toPortfolioTradingState(makeDefaultPortfolio(), {})
    expect(result.system_status).toBe('SAFE')
  })

  it('returns ALERT status when any asset is halted', () => {
    const asset1 = makeAssetState({ halt: { ...makeAssetState().halt, halted: true, reasons: ['drawdown'] } })
    const ts1 = toAssetTradingState('EURUSD', asset1)
    const result = toPortfolioTradingState(makeDefaultPortfolio(), { EURUSD: ts1 })
    expect(result.system_status).toBe('ALERT')
    expect(result.alerts).toContain('System halted')
  })

  it('returns MONITOR status when more than 3 assets are high risk', () => {
    const highRiskState = makeAssetState({
      metrics: { ...makeAssetState().metrics, drawdown: -20, monthly_pf: 0.5 },
    })
    const ts1 = toAssetTradingState('A', highRiskState)
    const ts2 = toAssetTradingState('B', highRiskState)
    const ts3 = toAssetTradingState('C', highRiskState)
    const ts4 = toAssetTradingState('D', highRiskState) // 4th high risk → triggers MONITOR
    const result = toPortfolioTradingState(makeDefaultPortfolio(), { A: ts1, B: ts2, C: ts3, D: ts4 })
    expect(result.system_status).toBe('MONITOR')
  })

  it('computes PnL total from portfolio total_return', () => {
    const portfolio = makeDefaultPortfolio()
    portfolio.total_return = 2.5
    const result = toPortfolioTradingState(portfolio, {})
    expect(result.pnl.total).toBe(2.5)
  })

  it('computes PnL efficiency as mean of per-asset efficiencies', () => {
    const ts1: AssetTradingState = {
      identity: 'A', position_state: 'CLOSED', direction: null,
      pnl_state: { unrealized: 0, avg_r: 0, efficiency: 'HIGH' },
      exit_state: { phase: 'STATIC', is_active: false, peak_mfe_r: null, retracement_pct: null, sl_is_dynamic: false, sl_confirmed_broker: false },
      risk_state: { level: 'LOW', drawdown_pressure: 0, drivers: [] },
      alpha_state: { mfe_capture_quality: null, reversal_probability: null },
      flags: [], recent_events: [],
    }
    const ts2: AssetTradingState = {
      identity: 'B', position_state: 'CLOSED', direction: null,
      pnl_state: { unrealized: 0, avg_r: 0, efficiency: 'NORMAL' },
      exit_state: { phase: 'STATIC', is_active: false, peak_mfe_r: null, retracement_pct: null, sl_is_dynamic: false, sl_confirmed_broker: false },
      risk_state: { level: 'LOW', drawdown_pressure: 0, drivers: [] },
      alpha_state: { mfe_capture_quality: null, reversal_probability: null },
      flags: [], recent_events: [],
    }
    // HIGH = 0.8, NORMAL = 0.5 → mean = 0.65
    const result = toPortfolioTradingState(makeDefaultPortfolio(), { A: ts1, B: ts2 })
    expect(result.pnl.efficiency).toBe(0.65)
  })

  it('computes drawdown from portfolio_drawdown', () => {
    const portfolio = makeDefaultPortfolio()
    portfolio.portfolio_drawdown = 0.03
    const result = toPortfolioTradingState(portfolio, {})
    expect(result.risk.drawdown).toBe(0.03)
  })

  it('computes net exposure as (long - short) / total', () => {
    const tsLong: AssetTradingState = {
      identity: 'A', position_state: 'OPEN', direction: 'LONG',
      pnl_state: { unrealized: 10, avg_r: 0, efficiency: 'NORMAL' },
      exit_state: { phase: 'STATIC', is_active: false, peak_mfe_r: null, retracement_pct: null, sl_is_dynamic: false, sl_confirmed_broker: false },
      risk_state: { level: 'LOW', drawdown_pressure: 0, drivers: [] },
      alpha_state: { mfe_capture_quality: null, reversal_probability: null },
      flags: [], recent_events: [],
    }
    const tsShort: AssetTradingState = {
      identity: 'B', position_state: 'OPEN', direction: 'SHORT',
      pnl_state: { unrealized: -5, avg_r: 0, efficiency: 'NORMAL' },
      exit_state: { phase: 'STATIC', is_active: false, peak_mfe_r: null, retracement_pct: null, sl_is_dynamic: false, sl_confirmed_broker: false },
      risk_state: { level: 'LOW', drawdown_pressure: 0, drivers: [] },
      alpha_state: { mfe_capture_quality: null, reversal_probability: null },
      flags: [], recent_events: [],
    }
    // long=1, short=1, total=2 → net = (1-1)/2 = 0
    const result = toPortfolioTradingState(makeDefaultPortfolio(), { A: tsLong, B: tsShort })
    expect(result.risk.net_exposure).toBe(0)
  })

  it('computes concentration risk from position_concentration skew', () => {
    const portfolio = makeDefaultPortfolio()
    portfolio.position_concentration = { long: 1, short: 0, total: 1, skew: 1, dominant_side: 'long', threshold: 0.75, alert: false }
    const result = toPortfolioTradingState(portfolio, {})
    // abs(1) > 0.7 → HIGH
    expect(result.risk.concentration_risk).toBe('HIGH')

    portfolio.position_concentration = { long: 3, short: 2, total: 5, skew: 0.2, dominant_side: 'long', threshold: 0.75, alert: false }
    const result2 = toPortfolioTradingState(portfolio, {})
    // abs(0.2) < 0.4 → LOW
    expect(result2.risk.concentration_risk).toBe('LOW')
  })

  it('sets MT5 sync to HEALTHY when connected, DEGRADED when not', () => {
    const result = toPortfolioTradingState(makeDefaultPortfolio(), {}, { mt5: { connected: true } })
    expect(result.execution.mt5_sync).toBe('HEALTHY')

    const result2 = toPortfolioTradingState(makeDefaultPortfolio(), {}, {})
    expect(result2.execution.mt5_sync).toBe('DEGRADED')
  })

  it('sets SL sync integrity to WARNING when an asset has dynamic unconfirmed SL', () => {
    const tsUnconfirmed: AssetTradingState = {
      identity: 'A', position_state: 'OPEN', direction: 'LONG',
      pnl_state: { unrealized: 10, avg_r: 0, efficiency: 'NORMAL' },
      exit_state: { phase: 'TRAILING', is_active: true, peak_mfe_r: null, retracement_pct: null, sl_is_dynamic: true, sl_confirmed_broker: false },
      risk_state: { level: 'LOW', drawdown_pressure: 0, drivers: [] },
      alpha_state: { mfe_capture_quality: null, reversal_probability: null },
      flags: [], recent_events: [],
    }
    const result = toPortfolioTradingState(makeDefaultPortfolio(), { A: tsUnconfirmed })
    expect(result.execution.sl_sync_integrity).toBe('WARNING')
    expect(result.alerts).toContain('Broker SL sync may be degraded')
  })

  it('computes edge trend from reversal rate', () => {
    const portfolio = makeDefaultPortfolio()
    portfolio.edge_health = {
      n_trades: 20, n_losers: 5, n_reversal_candidates: 2,
      reversal_rate: 0.1, warning_threshold: 0.15, alert: false,
      mean_mfe_r: null, median_mfe_r: null,
    }
    const result = toPortfolioTradingState(portfolio, {})
    // reversal_rate < 0.15 → EXPANDING
    expect(result.alpha.edge_trend).toBe('EXPANDING')

    portfolio.edge_health.reversal_rate = 0.25
    const result2 = toPortfolioTradingState(portfolio, {})
    // reversal_rate between 0.15 and 0.35 → STABLE
    expect(result2.alpha.edge_trend).toBe('STABLE')

    portfolio.edge_health.reversal_rate = 0.4
    const result3 = toPortfolioTradingState(portfolio, {})
    // reversal_rate > 0.35 → DECAYING
    expect(result3.alpha.edge_trend).toBe('DECAYING')
  })

  it('returns STABLE edge trend when reversal_rate is null', () => {
    const result = toPortfolioTradingState(makeDefaultPortfolio(), {})
    expect(result.alpha.edge_trend).toBe('STABLE')
    expect(result.alpha.reversal_rate).toBeNull()
  })

  it('alerts on elevated drawdown (> 5%)', () => {
    const portfolio = makeDefaultPortfolio()
    portfolio.portfolio_drawdown = 0.06
    const result = toPortfolioTradingState(portfolio, {})
    expect(result.alerts).toContain('Portfolio drawdown elevated')
  })

  it('builds top 3 risks from driver frequency across assets', () => {
    const tsDrawdown: AssetTradingState = {
      identity: 'A', position_state: 'CLOSED', direction: null,
      pnl_state: { unrealized: 0, avg_r: 0, efficiency: 'NORMAL' },
      exit_state: { phase: 'STATIC', is_active: false, peak_mfe_r: null, retracement_pct: null, sl_is_dynamic: false, sl_confirmed_broker: false },
      risk_state: { level: 'HIGH', drawdown_pressure: 0.9, drivers: ['drawdown'] },
      alpha_state: { mfe_capture_quality: null, reversal_probability: null },
      flags: [], recent_events: [],
    }
    const tsTripwire: AssetTradingState = {
      identity: 'B', position_state: 'CLOSED', direction: null,
      pnl_state: { unrealized: 0, avg_r: 0, efficiency: 'NORMAL' },
      exit_state: { phase: 'STATIC', is_active: false, peak_mfe_r: null, retracement_pct: null, sl_is_dynamic: false, sl_confirmed_broker: false },
      risk_state: { level: 'HIGH', drawdown_pressure: 0.9, drivers: ['drawdown', 'tripwire'] },
      alpha_state: { mfe_capture_quality: null, reversal_probability: null },
      flags: [], recent_events: [],
    }
    const result = toPortfolioTradingState(makeDefaultPortfolio(), { A: tsDrawdown, B: tsTripwire })
    expect(result.top_3_risks.length).toBeGreaterThan(0)
    // 'drawdown' appears in 2 assets, 'tripwire' in 1
    expect(result.top_3_risks[0].title).toBe('Drawdown pressure high')
  })
})
