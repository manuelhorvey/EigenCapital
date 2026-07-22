import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import HaltConditions from '../HaltConditions'

const mockFetch = vi.fn()

vi.mock('../../lib/api', () => ({
  fetchApi: (...args: unknown[]) => mockFetch(...args),
}))

vi.mock('../../hooks/useToast', () => ({
  useToast: () => ({ toast: vi.fn(), toasts: [], dismiss: vi.fn(), clear: vi.fn() }),
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

function makeBundle(overrides: {
  drawdown?: number
  portfolioDrawdown?: number
  monthlyPf?: number
  droughtHalted?: boolean
  driftHalted?: boolean
  haltConditions?: Record<string, number>
}) {
  const {
    drawdown = -0.02,
    portfolioDrawdown = 0,
    monthlyPf = 1.2,
    droughtHalted = false,
    driftHalted = false,
    haltConditions = {},
  } = overrides

  const assets: Record<string, any> = {
    EURUSD: {
      metrics: {
        asset: 'EURUSD', current_value: 100_000, settled_value: 100_000, mtm_value: 100_000,
        total_return: 2.5, settled_return: 0, mtm_return: 2.5, drawdown,
        profit_factor: 1.2, win_rate: 0.55, n_trades: 12, n_signals: 45,
        signal_distribution: { BUY: 30, SELL: 10, FLAT: 5 },
        mean_confidence: 0.6, mean_prob_long: 0.6, mean_prob_short: 0.4,
        current_price: 1.1234, last_signal_date: '2026-07-05T00:00:00Z', monthly_pf: monthlyPf,
        position: null, current_sl_mult: 2.5, current_tp_mult: 1.5, trade_log: [],
        feature_stability: { jaccard_top_10: null, spearman_rank_corr: null, penalty: 0, window_id: null },
        exit_reasons: { tp_rate: 0.3, sl_rate: 0.2, breakeven_rate: 0.1, flip_rate: 0.1, expiry_rate: 0.1, avg_r: 0.8 },
        archetype_stats: {}, meta_inference: null, scale_out_active: false,
        remaining_fraction: 1, scale_out_tiers: null,
        psi_drift: { per_feature: [], worst_classification: '', moderate_count: 0, severe_count: 0, psi_ok: true, penalty: 0 },
        sharpe_ratio: 0.75, psr_gt_0: 0.82, psr_gt_1: 0.45, min_trl: null, crs: null, hhi: null,
      },
      halt: {
        halted: droughtHalted || driftHalted,
        reasons: [
          ...(droughtHalted ? ['drought'] : []),
          ...(driftHalted ? ['drift'] : []),
        ],
        hard_reasons: [
          ...(droughtHalted ? ['drought'] : []),
          ...(driftHalted ? ['drift'] : []),
        ],
        soft_warnings: [],
        drawdown_ok: true, monthly_pf_ok: true, drought_ok: !droughtHalted,
        drift_ok: !driftHalted, narrative_ok: true, liquidity_ok: true, psi_ok: true,
      },
      validity_state: 'LONG' as const, validity_exposure: 1,
      last_signal: null, gate_override: false, signal_flip: false,
      final_signal: 'BUY' as const, execution_state: 'idle',
      sl_mult: 2, tp_mult: 2, meta_confidence: null, meta_decision: null,
      feature_stability_jaccard: null, feature_stability_spearman: null,
      sell_only: false, tripwire_active: false,
      liquidity_regime: 'NORMAL', liquidity_sl_mult: 1, liquidity_size_scalar: 1,
      narrative_sl_mult: 1, narrative_size_scalar: 1,
      narrative_regime: null, narrative_stale: false,
      regime_geometry: {}, soft_warnings: [],
      stop_out_last_side: null, stop_out_last_cycle: null,
      last_regime_long_prob: null, last_regime_label: null,
      sizing_chain: null, total_exits: 0, sl_exits: 0, sl_hit_rate: null,
    },
  }

  return {
    meta: {
      version: 'v1', server_time: '', status: 'ok' as const,
      snapshot_time: '', snapshot_sequence_id: 0, max_live_age_seconds: null, request_id: '',
    },
    snapshot: {
      contract_version: 7, sequence_id: 1, schema_version: '1.0.0', timestamp: '2026-07-05T00:00:00Z',
      portfolio: {
        total_value: 100_000, mtm_value: 100_000, total_return: 2.5, capital: 100_000,
        realized_value: 100_000, realized_return: 1.5, unrealized_pnl: 500,
        days_running: 30, runtime_hours: 720, start_date: '2026-06-07',
        start_datetime: '2026-06-07T00:00:00Z', last_update: null,
        deployment_cleared: false, allocations: { EURUSD: 0.05 },
        open_positions: 1, closed_trades: 15,
        portfolio_drawdown: portfolioDrawdown,
      },
      assets,
      open_positions: {},
      engine_status: { initialized: true, last_update: '', start_time: '' },
      halt_conditions: {
        drawdown: haltConditions.drawdown ?? -0.08,
        monthly_pf: haltConditions.monthly_pf ?? 0.7,
        signal_drought: haltConditions.signal_drought ?? 30,
        prob_drift: haltConditions.prob_drift ?? 0.15,
      },
    },
    live: {
      health: {
        fetch_time: '', fetch_age_seconds: 0, is_fresh: true, assets: {},
        system_health: { mean_health_score: 1, n_assets: 1, n_healthy: 1, n_degraded: 0, n_critical: 0, healthiest_asset: 'EURUSD', weakest_asset: 'EURUSD' },
      },
      mt5: { fetch_time: '', fetch_age_seconds: 0, is_fresh: true, connected: true, status: 'CONNECTED' as const, last_heartbeat: null, account: null },
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

describe('HaltConditions — all-passing state', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders all four cards with green check icons when all conditions pass', async () => {
    mockFetch.mockResolvedValue(makeBundle({}))
    const { wrapper } = withQueryClient()
    const { container } = render(<HaltConditions />, { wrapper })

    // Wait for data to render
    const maxDD = await screen.findByText('Max Drawdown')
    expect(maxDD).toBeInTheDocument()

    // All four card labels should be present
    expect(screen.getByText('Monthly PF')).toBeInTheDocument()
    expect(screen.getByText('Signal Drought')).toBeInTheDocument()
    expect(screen.getByText('Prob Drift')).toBeInTheDocument()

    // All should show green check (Check icon rendered)
    // Check icons are rendered when pass=true
    const checkIcons = container.querySelectorAll('svg')
    // Each card has an icon (Check or X) — all should be Check (green)
    expect(checkIcons.length).toBeGreaterThanOrEqual(4)

    // No "asset halted" alert
    expect(screen.queryByText(/halted/)).toBeNull()
  })
})

describe('HaltConditions — some-failing state', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows red X icons and threshold warnings when drawdown and drought fail', async () => {
    mockFetch.mockResolvedValue(makeBundle({
      portfolioDrawdown: -0.0015,  // fraction → -0.15% after * 100
      droughtHalted: true,
    }))
    const { wrapper } = withQueryClient()
    render(<HaltConditions />, { wrapper })

    // Wait for data
    await screen.findByText('Max Drawdown')

    // Drawdown value shows -0.15% (portfolio_drawdown fraction * 100)
    expect(screen.getByText(/-0\.15%/)).toBeInTheDocument()

    // Signal drought shows "Halted" (failing)
    expect(screen.getByText('Halted')).toBeInTheDocument()

    // "1 asset halted" alert should appear
    expect(screen.getByText(/1 asset halted/)).toBeInTheDocument()
  })

  it('shows both drought and drift halted when both fail', async () => {
    mockFetch.mockResolvedValue(makeBundle({
      droughtHalted: true,
      driftHalted: true,
    }))
    const { wrapper } = withQueryClient()
    render(<HaltConditions />, { wrapper })

    await screen.findByText('Max Drawdown')

    // Both Signal Drought and Prob Drift show "Halted"
    const haltedElements = screen.getAllByText('Halted')
    expect(haltedElements.length).toBe(2)

    // "1 asset halted" (same asset halted for both reasons)
    expect(screen.getByText(/1 asset halted/)).toBeInTheDocument()
  })
})
