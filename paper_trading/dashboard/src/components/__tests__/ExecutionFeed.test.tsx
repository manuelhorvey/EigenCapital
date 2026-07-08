import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import ExecutionFeed from '../ExecutionFeed'

// Mock useSelectedAsset
const mockSetSelectedAsset = vi.fn()
vi.mock('../../hooks/useSelectedAsset', () => ({
  useSelectedAsset: () => ({
    selectedAsset: null,
    setSelectedAsset: mockSetSelectedAsset,
    deepDiveAsset: null,
    setDeepDiveAsset: vi.fn(),
    deepDiveOpen: false,
  }),
}))

// Mock useSystemSnapshot
const mockUseSystemSnapshot = vi.fn()
vi.mock('../../hooks/useSystemSnapshot', () => ({
  useSystemSnapshot: (select?: any) => {
    if (select) {
      // If a selector is provided, call it with the mock data
      const result = mockUseSystemSnapshot()
      if (result.data) return { data: select(result.data) }
    }
    return mockUseSystemSnapshot()
  },
}))

// Mock formatTimeAgo to return consistent values
vi.mock('../../utils/format', () => ({
  formatTimeAgo: () => '2s ago',
  formatAssetPrice: (v: number) => String(v),
  safeToFixed: (v: number, d: number) => v.toFixed(d),
  confidenceToPercent: (v: number) => v <= 1 ? v * 100 : v,
}))

function makeBundle(overrides: Record<string, unknown> = {}) {
  return {
    data: {
      snapshot: {
        timestamp: '2026-07-05T00:00:00Z',
        sequence_id: 42,
        contract_version: 7,
        schema_version: '1.0.0',
        portfolio: {
          allocations: { EURUSD: 0.05, GBPUSD: 0.03, USDJPY: 0.04 },
          total_value: 100000,
          total_return: 2.5,
          open_positions: 2,
          closed_trades: 15,
          capital: 100000,
          mtm_value: 102500,
          realized_value: 100000,
          realized_return: 1.5,
          unrealized_pnl: 500,
          days_running: 30,
          runtime_hours: 720,
          start_date: '2026-06-07',
          start_datetime: '2026-06-07T00:00:00Z',
          last_update: '2026-07-05T00:00:00Z',
          deployment_cleared: false,
        },
        engine_status: { initialized: true, last_update: '', start_time: '2026-06-07T00:00:00Z' },
        halt_conditions: { drawdown: 0, monthly_pf: 0, signal_drought: 0, prob_drift: 0 },
        assets: {
          EURUSD: {
            last_signal: { date: '2026-07-05T00:00:00Z', prob_long: 0.65, prob_short: 0.35, signal: 'BUY', confidence: 0.65, close_price: 1.1234 },
            final_signal: 'BUY',
            halt: { halted: false, reasons: [], hard_reasons: [], soft_warnings: [], drawdown_ok: true, monthly_pf_ok: true, drought_ok: true, drift_ok: true, narrative_ok: true, liquidity_ok: true, psi_ok: true },
            execution_state: 'idle',
            sizing_chain: { final_pct: 0.05 },
            sell_only: false,
            tripwire_active: false,
            metrics: { asset: 'EURUSD', current_value: 100000, settled_value: 100000, mtm_value: 100000, total_return: 2.5, settled_return: 0, mtm_return: 2.5, drawdown: -0.5, profit_factor: 1.2, win_rate: 0.55, n_trades: 12, n_signals: 45, signal_distribution: { BUY: 30, SELL: 10, FLAT: 5 }, mean_confidence: 0.6, mean_prob_long: 0.6, mean_prob_short: 0.4, current_price: 1.1234, last_signal_date: '2026-07-05T00:00:00Z', monthly_pf: 1.5, position: null, current_sl_mult: 2.5, current_tp_mult: 1.5, trade_log: [], feature_stability: { jaccard_top_10: 0.85, spearman_rank_corr: 0.72, penalty: 0.05, window_id: 'w1' }, exit_reasons: { tp_rate: 0.3, sl_rate: 0.2, breakeven_rate: 0.1, flip_rate: 0.1, expiry_rate: 0.1, avg_r: 0.8 }, archetype_stats: {}, meta_inference: null, scale_out_active: false, remaining_fraction: 1, scale_out_tiers: null, psi_drift: { per_feature: [], worst_classification: '', moderate_count: 0, severe_count: 0, psi_ok: true, penalty: 0 }, sharpe_ratio: 0.75, psr_gt_0: 0.82, psr_gt_1: 0.45, min_trl: 3.2, crs: 0.6, hhi: 0.12 },
            validity_state: 'GREEN',
            validity_exposure: 1,
            gate_override: false,
            signal_flip: false,
            sl_mult: 2,
            tp_mult: 2,
            meta_confidence: null,
            meta_decision: null,
            feature_stability_jaccard: 0.85,
            feature_stability_spearman: 0.72,
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
            total_exits: 0,
            sl_exits: 0,
            sl_hit_rate: null,
          },
          GBPUSD: {
            last_signal: { date: '2026-07-05T00:00:00Z', prob_long: 0.35, prob_short: 0.65, signal: 'SELL', confidence: 0.58, close_price: 1.2650 },
            final_signal: 'SELL',
            halt: { halted: true, reasons: ['drawdown'], hard_reasons: ['drawdown'], soft_warnings: [], drawdown_ok: false, monthly_pf_ok: true, drought_ok: true, drift_ok: true, narrative_ok: true, liquidity_ok: true, psi_ok: true },
            execution_state: 'halted',
            sizing_chain: null,
            sell_only: true,
            tripwire_active: true,
            metrics: { ...makeMetrics('GBPUSD', 1.2650) },
            validity_state: 'RED',
            validity_exposure: 0,
            gate_override: false,
            signal_flip: false,
            sl_mult: 2,
            tp_mult: 2,
            meta_confidence: null,
            meta_decision: null,
            feature_stability_jaccard: null,
            feature_stability_spearman: null,
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
          },
        },
      },
      live: {
        health: { fetch_time: '', fetch_age_seconds: 0, is_fresh: true, assets: {}, system_health: { mean_health_score: 0.9, n_assets: 2, n_healthy: 2, n_degraded: 0, n_critical: 0, healthiest_asset: 'EURUSD', weakest_asset: 'GBPUSD' } },
        mt5: { fetch_time: '', fetch_age_seconds: 0, is_fresh: true, connected: true, status: 'CONNECTED' as const, last_heartbeat: null, account: null },
      },
      meta: { version: '1.0', server_time: '', status: 'ok' as const, snapshot_time: '', snapshot_sequence_id: 42, max_live_age_seconds: null, request_id: '' },
    },
    isPending: false,
    ...overrides,
  }
}

function makeMetrics(asset: string, price: number) {
  return {
    asset, current_value: 100000, settled_value: 100000, mtm_value: 100000,
    total_return: 0, settled_return: 0, mtm_return: 0, drawdown: 0,
    profit_factor: null, win_rate: 0, n_trades: 0, n_signals: 0,
    signal_distribution: { BUY: 0, SELL: 0, FLAT: 0 },
    mean_confidence: 0, mean_prob_long: 0.5, mean_prob_short: 0.5,
    current_price: price, last_signal_date: null, monthly_pf: null,
    position: null, current_sl_mult: 2, current_tp_mult: 2,
    trade_log: [],
    feature_stability: { jaccard_top_10: null, spearman_rank_corr: null, penalty: 0, window_id: null },
    exit_reasons: { tp_rate: 0, sl_rate: 0, breakeven_rate: 0, flip_rate: 0, expiry_rate: 0, avg_r: 0 },
    archetype_stats: {}, meta_inference: null, scale_out_active: false,
    remaining_fraction: 1, scale_out_tiers: null,
    psi_drift: { per_feature: [], worst_classification: '', moderate_count: 0, severe_count: 0, psi_ok: true, penalty: 0 },
    sharpe_ratio: null, psr_gt_0: null, psr_gt_1: null, min_trl: null, crs: null, hhi: null,
  }
}

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('ExecutionFeed', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseSystemSnapshot.mockReturnValue(makeBundle())
  })

  it('renders skeleton when loading', () => {
    mockUseSystemSnapshot.mockReturnValue({ data: null, isPending: true })
    renderWithQuery(<ExecutionFeed />)
    const skeletons = document.querySelectorAll('.skeleton, .skeleton-shimmer')
    expect(skeletons.length).toBeGreaterThan(0)
  })

  it('renders empty state when no assets', () => {
    mockUseSystemSnapshot.mockReturnValue({ data: { snapshot: { assets: {}, portfolio: { allocations: {} } } }, isPending: false })
    renderWithQuery(<ExecutionFeed />)
    expect(screen.getByText('Waiting for execution data\u2026')).toBeInTheDocument()
  })

  it('renders section header', () => {
    renderWithQuery(<ExecutionFeed />)
    expect(screen.getByText(/Last Cycle/)).toBeInTheDocument()
  })

  it('shows timestamp in header', () => {
    renderWithQuery(<ExecutionFeed />)
    expect(screen.getByText('2s ago')).toBeInTheDocument()
  })

  it('renders asset names in table', () => {
    renderWithQuery(<ExecutionFeed />)
    expect(screen.getByText('EURUSD')).toBeInTheDocument()
    expect(screen.getByText('GBPUSD')).toBeInTheDocument()
  })

  it('renders signal badges', () => {
    renderWithQuery(<ExecutionFeed />)
    expect(screen.getByText('LONG')).toBeInTheDocument()
    expect(screen.getByText('SHORT')).toBeInTheDocument()
  })

  it('shows HALTED status for halted assets', () => {
    renderWithQuery(<ExecutionFeed />)
    expect(screen.getByText('HALTED')).toBeInTheDocument()
  })

  it('shows PASS status for non-halted assets', () => {
    renderWithQuery(<ExecutionFeed />)
    const passElements = screen.getAllByText('PASS')
    expect(passElements.length).toBeGreaterThan(0)
  })

  it('shows blocked count when assets are halted', () => {
    renderWithQuery(<ExecutionFeed />)
    expect(screen.getByText('1 blocked')).toBeInTheDocument()
  })

  it('shows size percentage when sizing_chain is available', () => {
    renderWithQuery(<ExecutionFeed />)
    // EURUSD has sizing_chain.final_pct = 0.05 → 5.0%
    expect(screen.getByText('5.0%')).toBeInTheDocument()
  })

  it('shows dash when size is not available', () => {
    renderWithQuery(<ExecutionFeed />)
    const dashes = screen.getAllByText('\u2014')
    expect(dashes.length).toBeGreaterThan(0)
  })

  it('shows abort gate detail for halted assets', () => {
    renderWithQuery(<ExecutionFeed />)
    expect(screen.getByText('drawdown')).toBeInTheDocument()
  })

  it('calls setSelectedAsset on row click', () => {
    renderWithQuery(<ExecutionFeed />)
    fireEvent.click(screen.getByText('EURUSD'))
    expect(mockSetSelectedAsset).toHaveBeenCalledWith('EURUSD')
  })

  it('limits to 18 rows by default when more than 18 assets', () => {
    // Make bundle with 20 assets
    const bundle = makeBundle()
    const assets: Record<string, any> = {}
    for (let i = 0; i < 20; i++) {
      const name = `ASSET${i}`
      assets[name] = {
        ...bundle.data.snapshot.assets.EURUSD,
        metrics: {
          ...bundle.data.snapshot.assets.EURUSD.metrics,
          asset: name,
          current_price: 1.0,
        },
        last_signal: { ...bundle.data.snapshot.assets.EURUSD.last_signal, signal: i % 2 === 0 ? 'BUY' : 'SELL' },
        halt: { ...bundle.data.snapshot.assets.EURUSD.halt },
      }
      bundle.data.snapshot.portfolio.allocations[name] = 0.01
    }
    bundle.data.snapshot.assets = assets
    mockUseSystemSnapshot.mockReturnValue(bundle)

    renderWithQuery(<ExecutionFeed />)
    // Show more button should appear
    expect(screen.getByText(/Show all 20 assets/)).toBeInTheDocument()
  })

  it('shows all assets when "Show all" clicked', () => {
    const bundle = makeBundle()
    const assets: Record<string, any> = {}
    for (let i = 0; i < 20; i++) {
      const name = `ASSET${i}`
      assets[name] = {
        ...bundle.data.snapshot.assets.EURUSD,
        metrics: {
          ...bundle.data.snapshot.assets.EURUSD.metrics,
          asset: name,
          current_price: 1.0,
        },
        last_signal: { ...bundle.data.snapshot.assets.EURUSD.last_signal, signal: i % 2 === 0 ? 'BUY' : 'SELL' },
        halt: { ...bundle.data.snapshot.assets.EURUSD.halt },
      }
      bundle.data.snapshot.portfolio.allocations[name] = 0.01
    }
    bundle.data.snapshot.assets = assets
    mockUseSystemSnapshot.mockReturnValue(bundle)

    renderWithQuery(<ExecutionFeed />)
    fireEvent.click(screen.getByText(/Show all 20 assets/))
    expect(screen.getByText('Show fewer')).toBeInTheDocument()
  })
})
