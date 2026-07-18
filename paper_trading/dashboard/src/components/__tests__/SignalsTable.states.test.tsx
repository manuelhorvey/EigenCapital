import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import SignalsTable from '../SignalsTable'

const mockFetch = vi.fn()

vi.mock('../../lib/api', () => ({
  fetchApi: (...args: unknown[]) => mockFetch(...args),
}))

vi.mock('../../hooks/useSelectedAsset', () => ({
  useSelectedAsset: vi.fn(() => ({
    selectedAsset: null,
    setSelectedAsset: vi.fn(),
    deepDiveAsset: null,
    setDeepDiveAsset: vi.fn(),
  })),
}))

vi.mock('../../hooks/useToast', () => ({
  useToast: () => ({ toast: vi.fn(), toasts: [], dismiss: vi.fn(), clear: vi.fn() }),
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

function emptyBundle() {
  return {
    meta: {
      version: 'v1', server_time: '', status: 'ok' as const,
      snapshot_time: '', snapshot_sequence_id: 0, max_live_age_seconds: null, request_id: '',
    },
    snapshot: {
      contract_version: 1, sequence_id: 1, schema_version: '1.0.0', timestamp: '',
      portfolio: {
        total_value: 0, total_return: 0, capital: 0, allocations: {},
        mtm_value: 0, unrealized_pnl: 0, realized_value: 0, realized_return: 0,
        days_running: 0, runtime_hours: 0, start_date: '', start_datetime: '',
        last_update: null, deployment_cleared: false, open_positions: 0, closed_trades: 0,
      },
      assets: {},
      engine_status: { initialized: true, last_update: '', start_time: '' },
      halt_conditions: { drawdown: 0, monthly_pf: 0, signal_drought: 0, prob_drift: 0 },
    },
    live: {
      health: {
        fetch_time: '', fetch_age_seconds: 0, is_fresh: false, assets: {},
        system_health: { mean_health_score: 0, n_assets: 0, n_healthy: 0, n_degraded: 0, n_critical: 0, healthiest_asset: null, weakest_asset: null },
      },
      mt5: { fetch_time: '', fetch_age_seconds: 0, is_fresh: false, connected: false, status: 'UNKNOWN' as const, last_heartbeat: null, account: null },
    },
  }
}

function bundleWithOneAsset(assetName: string) {
  const b = emptyBundle()
  b.snapshot.assets = {
    [assetName]: {
      metrics: {
        asset: assetName, current_value: 100_000, settled_value: 100_000, mtm_value: 100_000,
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
        halted: false, reasons: [], hard_reasons: [], soft_warnings: [],
        drawdown_ok: true, monthly_pf_ok: true, drought_ok: true, drift_ok: true,
        narrative_ok: true, liquidity_ok: true, psi_ok: true,
      },
      validity_state: 'GREEN' as const, validity_exposure: 1, last_signal: null,
      gate_override: false, signal_flip: false, final_signal: null, execution_state: 'idle',
      sl_mult: 2, tp_mult: 2, meta_confidence: null, meta_decision: null,
      feature_stability_jaccard: null, feature_stability_spearman: null,
      sell_only: false, tripwire_active: false, liquidity_regime: 'NORMAL',
      liquidity_sl_mult: 1, liquidity_size_scalar: 1, narrative_sl_mult: 1,
      narrative_size_scalar: 1, narrative_regime: null, narrative_stale: false,
      regime_geometry: {}, soft_warnings: [], stop_out_last_side: null,
      stop_out_last_cycle: null, last_regime_long_prob: null, last_regime_label: null,
      sizing_chain: null, total_exits: 0, sl_exits: 0, sl_hit_rate: null,
    },
  }
  b.snapshot.portfolio.allocations = { [assetName]: 0.05 }
  return b
}

function withQueryClient() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
  return { wrapper, queryClient }
}

describe('SignalsTable — empty and filtered states', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows "No assets loaded" empty state when no assets exist', async () => {
    mockFetch.mockResolvedValue(emptyBundle())
    const { wrapper } = withQueryClient()
    render(<SignalsTable />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('No assets loaded')).toBeInTheDocument()
    })
  })

  it('shows "No assets match filter" empty state when search yields no results', async () => {
    mockFetch.mockResolvedValue(bundleWithOneAsset('EURUSD'))
    const { wrapper } = withQueryClient()
    render(<SignalsTable />, { wrapper })

    // Wait for data to render (EURUSD appears in both table and count badge)
    await waitFor(() => {
      expect(screen.getAllByText('EURUSD').length).toBeGreaterThanOrEqual(1)
    })

    // Now type a search that won't match
    const input = screen.getByPlaceholderText('Filter\u2026')
    input.focus()
    // Use fireEvent to type in the search input
    const { fireEvent } = await import('@testing-library/react')
    fireEvent.change(input, { target: { value: 'NONEXIST' } })

    // Wait for debounce (150ms) and check filtered empty state
    await waitFor(() => {
      // Should show the search-filtered empty message
      // The component renders EmptyState with filtered prop when search is active but no rows match
      expect(screen.getByText('No assets match filter')).toBeInTheDocument()
    }, { timeout: 1000 })
  })
})
