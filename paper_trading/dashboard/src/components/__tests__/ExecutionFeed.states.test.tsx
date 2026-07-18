import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import ExecutionFeed from '../ExecutionFeed'

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

const mockUseSystemSnapshot = vi.fn()
vi.mock('../../hooks/useSystemSnapshot', () => ({
  useSystemSnapshot: (select?: any) => {
    if (select) {
      const result = mockUseSystemSnapshot()
      if (result.data) return { data: select(result.data) }
    }
    return mockUseSystemSnapshot()
  },
}))

vi.mock('../../utils/format', () => ({
  formatTimeAgo: () => '0s ago',
  formatAssetPrice: (v: number) => String(v),
  safeToFixed: (v: number, d: number) => v.toFixed(d),
  confidenceToPercent: (v: number) => v <= 1 ? v * 100 : v,
}))

function makeBundleWithAssets(assetEntries: Array<{
  name: string
  signal: string
  gatesResult: 'PASS' | 'BLOCKED' | 'HALTED'
  halted?: boolean
}>) {
  const snapshot = {
    timestamp: '2026-07-05T00:00:00Z',
    sequence_id: 42,
    contract_version: 7,
    schema_version: '1.0.0',
    portfolio: {
      total_value: 100_000, total_return: 0, capital: 100_000,
      allocations: {} as Record<string, number>,
      mtm_value: 100_000, realized_value: 100_000, realized_return: 0,
      unrealized_pnl: 0, days_running: 0, runtime_hours: 0,
      start_date: '', start_datetime: '', last_update: null,
      deployment_cleared: false, open_positions: 0, closed_trades: 0,
    },
    engine_status: { initialized: true, last_update: '', start_time: '' },
    halt_conditions: { drawdown: 0, monthly_pf: 0, signal_drought: 0, prob_drift: 0 },
    assets: {} as Record<string, any>,
  }

  for (const entry of assetEntries) {
    snapshot.portfolio.allocations[entry.name] = 0.05
    const isHalted = entry.gatesResult === 'HALTED'
    const isBlocked = entry.gatesResult === 'BLOCKED'
    snapshot.assets[entry.name] = {
      metrics: {
        asset: entry.name, current_value: 100_000, settled_value: 100_000, mtm_value: 100_000,
        total_return: 0, settled_return: 0, mtm_return: 0, drawdown: 0,
        profit_factor: null, win_rate: 0, n_trades: 0, n_signals: 0,
        signal_distribution: { BUY: 0, SELL: 0, FLAT: 0 },
        mean_confidence: 0, mean_prob_long: 0.5, mean_prob_short: 0.5,
        current_price: null, last_signal_date: null, monthly_pf: null,
        position: null, current_sl_mult: 2, current_tp_mult: 2, trade_log: [],
        feature_stability: { jaccard_top_10: null, spearman_rank_corr: null, penalty: 0, window_id: null },
        exit_reasons: { tp_rate: 0, sl_rate: 0, breakeven_rate: 0, flip_rate: 0, expiry_rate: 0, avg_r: 0 },
        archetype_stats: {}, meta_inference: null, scale_out_active: false,
        remaining_fraction: 1, scale_out_tiers: null,
        psi_drift: { per_feature: [], worst_classification: '', moderate_count: 0, severe_count: 0, psi_ok: true, penalty: 0 },
        sharpe_ratio: null, psr_gt_0: null, psr_gt_1: null, min_trl: null, crs: null, hhi: null,
      },
      halt: {
        halted: isHalted,
        reasons: isHalted ? ['gate_aborted'] : [],
        hard_reasons: isHalted ? ['gate_aborted'] : [],
        soft_warnings: [],
        drawdown_ok: true, monthly_pf_ok: true, drought_ok: true, drift_ok: true,
        narrative_ok: true, liquidity_ok: true, psi_ok: true,
      },
      validity_state: 'GREEN' as const, validity_exposure: 1,
      last_signal: {
        date: '2026-07-05T00:00:00Z', prob_long: 0.5, prob_short: 0.5,
        signal: entry.signal, confidence: 0.5, close_price: 1.0,
      },
      gate_override: false, signal_flip: false,
      // BLOCKED condition: final_signal is null, but last_signal exists with a signal
      final_signal: isBlocked ? null : entry.signal,
      execution_state: isHalted ? 'halted' : 'idle', sl_mult: 2, tp_mult: 2,
      meta_confidence: null, meta_decision: null,
      feature_stability_jaccard: null, feature_stability_spearman: null,
      sell_only: false, tripwire_active: false,
      liquidity_regime: 'NORMAL', liquidity_sl_mult: 1, liquidity_size_scalar: 1,
      narrative_sl_mult: 1, narrative_size_scalar: 1,
      narrative_regime: null, narrative_stale: false,
      regime_geometry: {}, soft_warnings: [],
      stop_out_last_side: null, stop_out_last_cycle: null,
      last_regime_long_prob: null, last_regime_label: null,
      sizing_chain: entry.gatesResult === 'PASS' ? { final_pct: 0.05 } : null,
      total_exits: 0, sl_exits: 0, sl_hit_rate: null,
    }
  }

  return {
    data: { snapshot, meta: { version: '1.0', server_time: '', status: 'ok' as const, snapshot_time: '', snapshot_sequence_id: 42, max_live_age_seconds: null, request_id: '' }, live: { health: { fetch_time: '', fetch_age_seconds: 0, is_fresh: true, assets: {}, system_health: { mean_health_score: 0.9, n_assets: 0, n_healthy: 0, n_degraded: 0, n_critical: 0, healthiest_asset: null, weakest_asset: null } }, mt5: { fetch_time: '', fetch_age_seconds: 0, is_fresh: true, connected: true, status: 'CONNECTED' as const, last_heartbeat: null, account: null } } },
    isPending: false,
  }
}

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('ExecutionFeed — all-blocked state', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows all assets as BLOCKED with no PASS rows', () => {
    mockUseSystemSnapshot.mockReturnValue(makeBundleWithAssets([
      { name: 'EURUSD', signal: 'BUY', gatesResult: 'BLOCKED' },
      { name: 'GBPUSD', signal: 'SELL', gatesResult: 'BLOCKED' },
    ]))

    renderWithQuery(<ExecutionFeed />)

    // Both assets should show BLOCKED status
    const blocked = screen.getAllByText('BLOCKED')
    expect(blocked.length).toBe(2)

    // No PASS rows
    expect(screen.queryByText('PASS')).toBeNull()

    // Blocked count shows 2 blocked
    expect(screen.getByText('2 blocked')).toBeInTheDocument()
  })

  it('shows mixed PASS/HALTED states correctly', () => {
    mockUseSystemSnapshot.mockReturnValue(makeBundleWithAssets([
      { name: 'EURUSD', signal: 'BUY', gatesResult: 'PASS' },
      { name: 'GBPUSD', signal: 'SELL', gatesResult: 'HALTED' },
      { name: 'USDJPY', signal: 'BUY', gatesResult: 'PASS' },
    ]))

    renderWithQuery(<ExecutionFeed />)

    // Should have PASS rows
    const passElements = screen.getAllByText('PASS')
    expect(passElements.length).toBe(2)

    // Should have HALTED row
    expect(screen.getByText('HALTED')).toBeInTheDocument()

    // Blocked count shows 1 blocked (both BLOCKED and HALTED count as non-PASS)
    expect(screen.getByText('1 blocked')).toBeInTheDocument()
  })
})
