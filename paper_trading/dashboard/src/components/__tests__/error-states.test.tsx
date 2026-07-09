import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import ErrorBoundary from '../ErrorBoundary'
import ErrorScreen from '../ui/ErrorScreen'
import LoadingScreen from '../ui/LoadingScreen'
import SignalsTable from '../SignalsTable'
import TradeFeed from '../TradeFeed'
import OverviewTab from '../AssetDetailPanel/OverviewTab'
import GovernanceTab from '../AssetDetailPanel/GovernanceTab'
import DiagnosticsTab from '../AssetDetailPanel/DiagnosticsTab'
import SizingTab from '../AssetDetailPanel/SizingTab'
import type { z } from 'zod'
import { AssetStateSchema } from '../../lib/schemas'

type AssetState = z.infer<typeof AssetStateSchema>

// ── Mocks ─────────────────────────────────────────────────────────

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

vi.mock('../trades/TradeInspectorModal', () => ({
  default: vi.fn(() => null),
}))

function withQueryClient() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
  return { wrapper, queryClient }
}

// ── ErrorBoundary tests ───────────────────────────────────────────

describe('ErrorBoundary', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders children when no error occurs', () => {
    const { container } = render(
      <ErrorBoundary>
        <div data-testid="child">Hello world</div>
      </ErrorBoundary>,
    )
    expect(container.querySelector('[data-testid="child"]')).toBeTruthy()
    expect(screen.getByText('Hello world')).toBeInTheDocument()
  })

  it('catches errors and renders default fallback', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    const Throws = () => {
      throw new Error('Test boundary error')
    }

    render(
      <ErrorBoundary title="Test Section">
        <Throws />
      </ErrorBoundary>,
    )

    // Should render the PanelFallback with the title and error indicator
    expect(screen.getByText('Test Section — Error')).toBeInTheDocument()
    consoleSpy.mockRestore()
  })

  it('catches errors and renders custom fallback', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    const Throws = () => {
      throw new Error('Custom fallback error')
    }

    render(
      <ErrorBoundary fallback={<div data-testid="custom-fallback">Custom error UI</div>}>
        <Throws />
      </ErrorBoundary>,
    )

    expect(screen.getByText('Custom error UI')).toBeInTheDocument()
    consoleSpy.mockRestore()
  })

  it('catches errors and renders function-based fallback', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    const Throws = () => {
      throw new Error('Function fallback')
    }

    render(
      <ErrorBoundary fallback={(error: Error) => <div data-testid="fn-fallback">Caught: {error.message}</div>}>
        <Throws />
      </ErrorBoundary>,
    )

    expect(screen.getByText('Caught: Function fallback')).toBeInTheDocument()
    consoleSpy.mockRestore()
  })

  // ── Phase F: sanitization tests ───────────────────────────────

  it('sanitizes JWT tokens from error messages before logging', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    const Throws = () => {
      throw new Error('Auth failed: token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.kWpPkV0bq0.expired')
    }

    render(
      <ErrorBoundary title="Auth">
        <Throws />
      </ErrorBoundary>,
    )

    // Verify console received sanitised message (happens via captureError fallback when no Sentry DSN)
    expect(consoleSpy).toHaveBeenCalledWith('[ErrorBoundary]', 'Error', expect.stringContaining('[JWT]'))
    expect(consoleSpy).toHaveBeenCalledWith('[ErrorBoundary]', 'Error', expect.not.stringContaining('eyJhbGciOiJIUzI1NiJ9'))

    consoleSpy.mockRestore()
  })

  it('sanitizes API keys and secrets from error messages', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    const Throws = () => {
      throw new Error('API call failed: api_key=sk_live_abc123_def456')
    }

    render(
      <ErrorBoundary>
        <Throws />
      </ErrorBoundary>,
    )

    expect(consoleSpy).toHaveBeenCalledWith('[ErrorBoundary]', 'Error', expect.stringContaining('[REDACTED]'))
    expect(consoleSpy).toHaveBeenCalledWith('[ErrorBoundary]', 'Error', expect.not.stringContaining('sk_live_abc123_def456'))

    consoleSpy.mockRestore()
  })

  it('sanitizes file paths from error messages', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    const Throws = () => {
      throw new Error('File not found: /home/user/project/config/credentials.json')
    }

    render(
      <ErrorBoundary>
        <Throws />
      </ErrorBoundary>,
    )

    expect(consoleSpy).toHaveBeenCalledWith('[ErrorBoundary]', 'Error', expect.stringContaining('[PATH]'))
    expect(consoleSpy).toHaveBeenCalledWith('[ErrorBoundary]', 'Error', expect.not.stringContaining('/home/user/project'))

    consoleSpy.mockRestore()
  })

  it('does NOT modify normal error messages without sensitive data', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    const Throws = () => {
      throw new Error('Cannot read properties of undefined (reading "map")')
    }

    render(
      <ErrorBoundary>
        <Throws />
      </ErrorBoundary>,
    )

    expect(consoleSpy).toHaveBeenCalledWith('[ErrorBoundary]', 'Error', 'Cannot read properties of undefined (reading "map")')

    consoleSpy.mockRestore()
  })

  it('does not throw when captureError encounters a network error', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    const Throws = () => {
      throw new Error('Network error')
    }

    // Should not throw — captureError catches internally
    expect(() =>
      render(
        <ErrorBoundary>
          <Throws />
        </ErrorBoundary>,
      ),
    ).not.toThrow()

    consoleSpy.mockRestore()
  })
})

// ── ErrorScreen tests ─────────────────────────────────────────────

describe('ErrorScreen', () => {
  it('renders default title and message', () => {
    render(<ErrorScreen />)
    expect(screen.getByText('Engine Not Reachable')).toBeInTheDocument()
    expect(screen.getByText(/Make sure the paper trading engine is running/)).toBeInTheDocument()
  })

  it('renders custom title and message', () => {
    render(<ErrorScreen title="Custom Error" message="Something went wrong" />)
    expect(screen.getByText('Custom Error')).toBeInTheDocument()
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })

  it('renders retry button', () => {
    render(<ErrorScreen />)
    expect(screen.getByText('Retry connection')).toBeInTheDocument()
  })

  it('calls custom onRetry when button is clicked', () => {
    const onRetry = vi.fn()
    render(<ErrorScreen onRetry={onRetry} />)
    screen.getByText('Retry connection').click()
    expect(onRetry).toHaveBeenCalledOnce()
  })
})

// ── LoadingScreen tests ───────────────────────────────────────────

describe('LoadingScreen', () => {
  it('renders default title and subtitle', () => {
    render(<LoadingScreen />)
    expect(screen.getByText('Connecting to EigenCapital Engine')).toBeInTheDocument()
    expect(screen.getByText('Waiting for paper trading data…')).toBeInTheDocument()
  })

  it('renders custom title and subtitle', () => {
    render(<LoadingScreen title="Loading" subtitle="Please wait…" />)
    expect(screen.getByText('Loading')).toBeInTheDocument()
    expect(screen.getByText('Please wait…')).toBeInTheDocument()
  })
})

// ── SignalsTable error/loading states ─────────────────────────────

describe('SignalsTable — loading state', () => {
  it('shows table skeleton when data is pending', () => {
    mockFetch.mockImplementation(() => new Promise(() => {})) // never resolves
    const { wrapper } = withQueryClient()
    const { container } = render(<SignalsTable />, { wrapper })
    // Should render skeleton shimmer elements
    expect(container.querySelector('.skeleton-shimmer')).toBeTruthy()
  })
})

// ── TradeFeed error/loading states ────────────────────────────────

describe('TradeFeed — loading state', () => {
  it('shows table skeleton when data is pending', () => {
    mockFetch.mockImplementation(() => new Promise(() => {})) // never resolves
    const { wrapper } = withQueryClient()
    const { container } = render(<TradeFeed />, { wrapper })
    expect(container.querySelector('.skeleton-shimmer')).toBeTruthy()
  })
})

// ── AssetDetailPanel tabs — edge/null data handling ───────────────

function makeMinimalAssetState(overrides: Partial<AssetState> = {}): AssetState {
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
      ...overrides.metrics as object,
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
      ...overrides.halt as object,
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

describe('AssetDetailPanel tabs — edge/null data', () => {
  it('OverviewTab renders with minimal asset state', () => {
    const asset = makeMinimalAssetState()
    const { container } = render(<OverviewTab asset={asset} />)
    // Should render signal, confidence, price, etc. without crashing
    expect(container.textContent).toContain('FLAT')
    expect(container.textContent).toContain('—')
  })

  it('GovernanceTab renders with null psi_drift features', () => {
    const asset = makeMinimalAssetState()
    const { container } = render(<GovernanceTab asset={asset} />)
    expect(container.textContent).toContain('Validity')
  })

  it('GovernanceTab renders halted state with reasons', () => {
    const asset = makeMinimalAssetState({
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
        psi_ok: false,
      },
    })
    render(<GovernanceTab asset={asset} />)
    expect(screen.getByText(/drawdown; drift/)).toBeInTheDocument()
  })

  it('DiagnosticsTab renders with null feature_stability fields', () => {
    const asset = makeMinimalAssetState({
      metrics: {
        ...makeMinimalAssetState().metrics,
        feature_stability: { jaccard_top_10: null, spearman_rank_corr: null, penalty: 0, window_id: null },
      },
    })
    const { container } = render(<DiagnosticsTab asset={asset} />)
    // Should render without crashing — will show '—' for null values
    expect(container.textContent).toContain('—')
  })

  it('SizingTab renders with null sizing_chain', () => {
    const asset = makeMinimalAssetState()
    render(<SizingTab asset={asset} />)
    expect(screen.getByText('No entry attempted')).toBeInTheDocument()
  })

  it('SizingTab renders with scale-out tiers', () => {
    const asset = makeMinimalAssetState({
      metrics: {
        ...makeMinimalAssetState().metrics,
        scale_out_active: true,
        scale_out_tiers: [
          { fraction: 0.5, price: 1.12, filled: true, fill_price: 1.1205 },
          { fraction: 0.5, price: 1.13, filled: false, fill_price: null },
        ],
        remaining_fraction: 0.5,
      },
    })
    render(<SizingTab asset={asset} />)
    expect(screen.getByText(/Filled @/)).toBeInTheDocument()
    expect(screen.getByText(/Pending @/)).toBeInTheDocument()
  })
})
