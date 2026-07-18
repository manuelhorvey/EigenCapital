import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import SystemHealthSummary from '../SystemHealthSummary'

const mockFetch = vi.fn()

vi.mock('../../lib/api', () => ({
  fetchApi: (...args: unknown[]) => mockFetch(...args),
}))

vi.mock('../../hooks/useToast', () => ({
  useToast: () => ({ toast: vi.fn(), toasts: [], dismiss: vi.fn(), clear: vi.fn() }),
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

function makeStateBundle() {
  return {
    meta: {
      version: 'v1',
      server_time: '2026-07-05T00:00:00Z',
      status: 'ok',
      snapshot_time: '2026-07-05T00:00:00Z',
      snapshot_sequence_id: 42,
      max_live_age_seconds: 30,
      request_id: 'test-req',
    },
    snapshot: {
      contract_version: 7,
      sequence_id: 42,
      schema_version: '1.0.0',
      timestamp: '2026-07-05T00:00:00Z',
      portfolio: {
        capital: 100_000, total_value: 102_500, total_return: 2.5,
        mtm_value: 102_500, realized_value: 100_000, realized_return: 1.5,
        unrealized_pnl: 500, days_running: 30, runtime_hours: 720,
        start_date: '2026-06-07', start_datetime: '2026-06-07T00:00:00Z',
        last_update: '2026-07-05T00:00:00Z', deployment_cleared: false,
        allocations: { EURUSD: 0.05, GBPUSD: 0.03 },
        open_positions: 2, closed_trades: 15,
        win_rate: 0.55, n_trades: 15, n_signals: 60,
        mean_confidence: 0.6, mean_prob_long: 0.6, mean_prob_short: 0.4,
        current_price: null, last_signal_date: null, monthly_pf: 1.5,
        position: null, current_sl_mult: 2, current_tp_mult: 2,
        trade_log: [],
        feature_stability: { jaccard_top_10: null, spearman_rank_corr: null, penalty: 0, window_id: null },
        exit_reasons: { tp_rate: 0.3, sl_rate: 0.2, breakeven_rate: 0.1, flip_rate: 0.1, expiry_rate: 0.1, avg_r: 0.8 },
        archetype_stats: {}, meta_inference: null,
        scale_out_active: false, remaining_fraction: 1, scale_out_tiers: null,
        psi_drift: { per_feature: [], worst_classification: '', moderate_count: 0, severe_count: 0, psi_ok: true, penalty: 0 },
        sharpe_ratio: 0.75, psr_gt_0: 0.82, psr_gt_1: 0.45,
        min_trl: null, crs: null, hhi: null,
      },
      assets: {},
      open_positions: {},
      engine_status: { initialized: true, last_update: '', start_time: '' },
      halt_conditions: { drawdown: 0, monthly_pf: 0, signal_drought: 0, prob_drift: 0 },
    },
    live: {
      health: {
        fetch_time: '2026-07-05T00:00:00Z',
        fetch_age_seconds: 0,
        is_fresh: true,
        assets: {},
        system_health: { mean_health_score: 1, n_assets: 19, n_healthy: 19, n_degraded: 0, n_critical: 0, healthiest_asset: 'GC', weakest_asset: 'GC' },
      },
      mt5: {
        fetch_time: '2026-07-05T00:00:00Z',
        fetch_age_seconds: 0,
        is_fresh: true,
        connected: true,
        status: 'CONNECTED',
        last_heartbeat: '2026-07-05T00:00:00Z',
        account: { portfolio_value: 100_000 },
      },
    },
  }
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

describe('SystemHealthSummary — integration with /state-bundle.json', () => {
  beforeEach(() => {
    mockFetch.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows loading skeleton initially, then renders health data from bundle', async () => {
    mockFetch.mockResolvedValue(makeStateBundle())
    const { wrapper } = withQueryClient()
    const { container } = render(<SystemHealthSummary />, { wrapper })

    // Shows loading skeleton initially
    expect(container.querySelector('.skeleton-shimmer')).toBeTruthy()

    // After data resolves, shows the status badge
    await waitFor(() => {
      expect(screen.getByText('SAFE')).toBeInTheDocument()
    })
  })

  it('renders portfolio PnL from the bundle data', async () => {
    mockFetch.mockResolvedValue(makeStateBundle())
    const { wrapper } = withQueryClient()
    render(<SystemHealthSummary />, { wrapper })

    await waitFor(() => {
      // total_return is 2.5, PnL shows as +2.50%
      expect(screen.getByText('+2.50%')).toBeInTheDocument()
    })
  })

  it('renders MT5 sync status from live section', async () => {
    mockFetch.mockResolvedValue(makeStateBundle())
    const { wrapper } = withQueryClient()
    render(<SystemHealthSummary />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('HEALTHY')).toBeInTheDocument()
    })
  })

  it('renders "All systems nominal" when no alerts', async () => {
    mockFetch.mockResolvedValue(makeStateBundle())
    const { wrapper } = withQueryClient()
    render(<SystemHealthSummary />, { wrapper })

    await waitFor(() => {
      expect(screen.getByText('All systems nominal')).toBeInTheDocument()
    })
  })

  it('shows Edge Health from trading state derived data', async () => {
    mockFetch.mockResolvedValue(makeStateBundle())
    const { wrapper } = withQueryClient()
    render(<SystemHealthSummary />, { wrapper })

    // With no alpha data in the raw bundle, trading state defaults — check it renders
    await waitFor(() => {
      expect(screen.getByText(/Edge Health/)).toBeInTheDocument()
    })
  })
})
