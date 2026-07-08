import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ExecutionFeed from '../ExecutionFeed'

// ── Mocks ─────────────────────────────────────────────────────────

vi.mock('../../hooks/useSelectedAsset', () => ({
  useSelectedAsset: vi.fn(() => ({
    selectedAsset: null,
    setSelectedAsset: vi.fn(),
    deepDiveAsset: null,
    setDeepDiveAsset: vi.fn(),
  })),
}))

function makeAsset(overrides: Record<string, unknown> = {}) {
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
      win_rate: 0,
      n_trades: 0,
      n_signals: 0,
      signal_distribution: { BUY: 0, SELL: 0, FLAT: 0 },
      mean_confidence: 0,
      mean_prob_long: 0,
      mean_prob_short: 0,
      current_price: null,
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
    halt: { halted: false, reasons: [], hard_reasons: [], soft_warnings: [], drawdown_ok: true, monthly_pf_ok: true, drought_ok: true, drift_ok: true, narrative_ok: true, liquidity_ok: true, psi_ok: true },
    validity_state: 'GREEN',
    validity_exposure: 1,
    last_signal: { date: '2026-07-08T12:00:00', prob_long: 0.7, prob_short: 0.3, signal: 'BUY', confidence: 0.65, close_price: 1.1050 },
    gate_override: false,
    signal_flip: false,
    final_signal: 'BUY',
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

/** Build fake snapshot data as returned by useSystemSnapshot(systemSelectors.snapshot).
 *  The selector returns b.snapshot directly, so data IS the snapshot content. */
function makeSnapshotData(assets: Record<string, unknown> = {}) {
  return {
    data: {
      contract_version: 1,
      sequence_id: 1,
      schema_version: '1.0',
      timestamp: '2026-07-08T12:00:00Z',
      portfolio: {
        capital: 100_000,
        total_value: 100_000,
        total_return: 0,
        allocations: Object.keys(assets).reduce<Record<string, number>>(
          (acc, name) => { acc[name] = 5; return acc },
          {},
        ),
        closed_trades: 0,
      },
      assets,
      engine_status: { start_time: '2026-07-01T00:00:00Z' },
      halt_conditions: { drawdown: 0, monthly_pf: 0, signal_drought: 0, prob_drift: 0 },
    },
    isPending: false,
    isError: false,
    error: null,
  }
}

let mockSnapshot = makeSnapshotData({})

vi.mock('../../hooks/useSystemSnapshot', () => ({
  useSystemSnapshot: vi.fn(() => mockSnapshot),
}))

// ── Tests ──────────────────────────────────────────────────────────

describe('ExecutionFeed', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSnapshot = makeSnapshotData({})
  })

  it('shows skeleton when data is pending', () => {
    mockSnapshot = { data: undefined, isPending: true, isError: false, error: null } as never
    const { container } = render(<ExecutionFeed />)
    // Skeleton without shimmer prop renders <div class="skeleton ..." aria-hidden="true" />
    expect(container.querySelector('[aria-hidden="true"]')).toBeTruthy()
  })

  it('shows empty state when no assets', () => {
    render(<ExecutionFeed />)
    expect(screen.getByText('Waiting for execution data…')).toBeInTheDocument()
  })

  it('shows empty state when no allocated assets', () => {
    mockSnapshot = makeSnapshotData({
      EURUSD: makeAsset(),
    })
    // Override allocations to exclude EURUSD
    mockSnapshot.data.portfolio.allocations = {}
    render(<ExecutionFeed />)
    expect(screen.getByText('Waiting for execution data…')).toBeInTheDocument()
  })

  it('renders asset row with PASS gate and LONG signal', () => {
    mockSnapshot = makeSnapshotData({
      EURUSD: makeAsset({
        final_signal: 'BUY',
        last_signal: { date: '2026-07-08T12:00:00', prob_long: 0.7, prob_short: 0.3, signal: 'BUY', confidence: 0.65, close_price: 1.1050 },
        halt: { halted: false, reasons: [], hard_reasons: [], soft_warnings: [], drawdown_ok: true, monthly_pf_ok: true, drought_ok: true, drift_ok: true, narrative_ok: true, liquidity_ok: true, psi_ok: true },
        sizing_chain: { final_pct: 0.15 },
      }),
    })
    render(<ExecutionFeed />)

    expect(screen.getAllByText('EURUSD').length).toBeGreaterThan(0)
    expect(screen.getByText('LONG')).toBeInTheDocument()
    expect(screen.getByText('65')).toBeInTheDocument() // confidence * 100
    expect(screen.getByText('PASS')).toBeInTheDocument()
    expect(screen.getByText('15.0%')).toBeInTheDocument() // sizing_chain.final_pct * 100
  })

  it('renders SELL signal as SHORT badge', () => {
    mockSnapshot = makeSnapshotData({
      GBPUSD: makeAsset({
        final_signal: 'SELL',
        last_signal: { date: '2026-07-08T12:00:00', prob_long: 0.3, prob_short: 0.7, signal: 'SELL', confidence: 0.72, close_price: 1.2850 },
        sizing_chain: { final_pct: 0.10 },
      }),
    })
    render(<ExecutionFeed />)

    expect(screen.getAllByText('GBPUSD').length).toBeGreaterThan(0)
    expect(screen.getByText('SHORT')).toBeInTheDocument()
    expect(screen.getByText('72')).toBeInTheDocument() // confidence * 100
    expect(screen.getByText('10.0%')).toBeInTheDocument()
  })

  it('renders FLAT signal as FLAT badge when no final signal', () => {
    mockSnapshot = makeSnapshotData({
      EURJPY: makeAsset({
        final_signal: null,
        last_signal: { date: '2026-07-08T12:00:00', prob_long: 0.5, prob_short: 0.5, signal: 'FLAT', confidence: 0.5, close_price: 160.0 },
      }),
    })
    render(<ExecutionFeed />)

    expect(screen.getByText('FLAT')).toBeInTheDocument()
  })

  it('renders HALTED gate with reasons', () => {
    mockSnapshot = makeSnapshotData({
      USDJPY: makeAsset({
        halt: {
          halted: true,
          reasons: ['drawdown', 'drift'],
          hard_reasons: ['drawdown'],
          soft_warnings: [],
          drawdown_ok: false,
          monthly_pf_ok: true,
          drought_ok: true,
          drift_ok: false,
          narrative_ok: true,
          liquidity_ok: true,
          psi_ok: true,
        },
      }),
    })
    render(<ExecutionFeed />)

    expect(screen.getAllByText('USDJPY').length).toBeGreaterThan(0)
    expect(screen.getByText('HALTED')).toBeInTheDocument()
    expect(screen.getByText(/drawdown; drift/)).toBeInTheDocument()
  })

  it('renders BLOCKED gate when final_signal is null but signal exists', () => {
    mockSnapshot = makeSnapshotData({
      AUDUSD: makeAsset({
        final_signal: null,
        last_signal: { date: '2026-07-08T12:00:00', prob_long: 0.6, prob_short: 0.4, signal: 'BUY', confidence: 0.6, close_price: 0.6750 },
      }),
    })
    render(<ExecutionFeed />)

    expect(screen.getAllByText('AUDUSD').length).toBeGreaterThan(0)
    expect(screen.getByText('BLOCKED')).toBeInTheDocument()
    expect(screen.getByText('gate_aborted')).toBeInTheDocument()
  })

  it('shows dash for missing size when sizing_chain is null', () => {
    mockSnapshot = makeSnapshotData({
      NZDUSD: makeAsset({
        sizing_chain: null,
      }),
    })
    render(<ExecutionFeed />)

    // '—' appears in the size column AND the detail column when both are null
    const dashes = screen.getAllByText('—')
    expect(dashes.length).toBeGreaterThanOrEqual(1)
  })

  it('shows blocked count in header when some gates are not PASS', () => {
    mockSnapshot = makeSnapshotData({
      EURUSD: makeAsset({ final_signal: 'BUY' }),
      USDJPY: makeAsset({
        halt: {
          halted: true,
          reasons: ['drawdown'],
          hard_reasons: ['drawdown'],
          soft_warnings: [],
          drawdown_ok: false,
          monthly_pf_ok: true,
          drought_ok: true,
          drift_ok: true,
          narrative_ok: true,
          liquidity_ok: true,
          psi_ok: true,
        },
      }),
    })
    render(<ExecutionFeed />)

    expect(screen.getByText('1 blocked')).toBeInTheDocument()
  })

  it('shows "Show all" button when more than 18 assets', () => {
    const manyAssets: Record<string, unknown> = {}
    for (let i = 0; i < 20; i++) {
      const name = `ASSET${i.toString().padStart(2, '0')}`
      manyAssets[name] = makeAsset({ final_signal: 'BUY' })
    }
    mockSnapshot = makeSnapshotData(manyAssets)
    render(<ExecutionFeed />)

    const button = screen.getByText(/Show all 20 assets/)
    expect(button).toBeInTheDocument()

    // Click to expand using fireEvent (userEvent not installed)
    fireEvent.click(button)
    expect(screen.getByText('Show fewer')).toBeInTheDocument()
  })

  it('renders dash for null abortedGate when gate passes', () => {
    mockSnapshot = makeSnapshotData({
      EURUSD: makeAsset({ final_signal: 'BUY' }),
    })
    render(<ExecutionFeed />)

    // The detail column shows '—' when abortedGate is null and gate passes
    const dashes = screen.getAllByText('—')
    expect(dashes.length).toBeGreaterThan(0)
  })
})
