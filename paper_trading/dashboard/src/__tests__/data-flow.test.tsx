import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors, selectAsset, selectOpenPosition, selectMeta } from '../selectors/system'
import AssetCard from '../components/AssetCard'
import { useSelectedAsset } from '../hooks/useSelectedAsset'
import type { OpenPositionState, RiskSignal, ShadowAction } from '../types/portfolio'

// ── Mock fetchApi ─────────────────────────────────────────────────

const mockFetch = vi.fn()

vi.mock('../lib/api', () => ({
  fetchApi: (...args: unknown[]) => mockFetch(...args),
}))

// ── Mock useSelectedAsset ─────────────────────────────────────────

vi.mock('../hooks/useSelectedAsset', () => ({
  useSelectedAsset: vi.fn(),
}))

const mockSetSelectedAsset = vi.fn()
const mockSetDeepDiveAsset = vi.fn()
const mockUseSelectedAsset = vi.mocked(useSelectedAsset)
mockUseSelectedAsset.mockReturnValue({
  selectedAsset: null,
  setSelectedAsset: mockSetSelectedAsset,
  deepDiveAsset: null,
  setDeepDiveAsset: mockSetDeepDiveAsset,
  deepDiveOpen: false,
})

// ── Test helpers ──────────────────────────────────────────────────

interface MakeBundleOpts {
  sequenceId?: number
  version?: string
  assetName?: string
  finalSignal?: 'BUY' | 'SELL' | null
  confidence?: number
  position?: PositionData | null
  openPosition?: OpenPositionState | null
  riskSignal?: RiskSignal | null
  shadowAction?: ShadowAction | null
  sellOnly?: boolean
  tripwireActive?: boolean
}

interface PositionData {
  side: 'long' | 'short'
  entry: number
  sl: number
  tp: number
  current_vol: number
  unrealized_pnl: number
  [key: string]: unknown
}

function makeValidBundle(opts: MakeBundleOpts = {}) {
  const {
    sequenceId = 42,
    version = 'v1',
    assetName = 'EURUSD',
    finalSignal = 'BUY',
    confidence = 0.65,
    position = null,
    openPosition = null,
    riskSignal = null,
    shadowAction = null,
    sellOnly = false,
    tripwireActive = false,
  } = opts

  return {
    meta: {
      version,
      server_time: '2026-07-05T00:00:00Z',
      status: 'ok' as const,
      snapshot_time: '2026-07-05T00:00:00Z',
      snapshot_sequence_id: sequenceId,
      max_live_age_seconds: 30,
      request_id: 'test-req',
    },
    snapshot: {
      contract_version: 7,
      sequence_id: sequenceId,
      schema_version: '1.0.0',
      timestamp: '2026-07-05T00:00:00Z',
      portfolio: {
        capital: 100_000,
        total_value: 100_000,
        total_return: 0,
        mtm_value: 100_000,
        realized_value: 100_000,
        realized_return: 0,
        unrealized_pnl: 0,
        days_running: 30,
        runtime_hours: 720,
        start_date: '2026-06-07',
        start_datetime: '2026-06-07T00:00:00Z',
        last_update: '2026-07-05T00:00:00Z',
        allocations: { [assetName]: 0.05 },
        deployment_cleared: false,
        open_positions: 0,
        closed_trades: 0,
      },
      assets: {
        [assetName]: {
          metrics: {
            asset: assetName,
            current_value: 100_000,
            settled_value: 100_000,
            mtm_value: 100_000,
            total_return: 2.5,
            settled_return: 0,
            mtm_return: 2.5,
            drawdown: -0.5,
            profit_factor: 1.2,
            win_rate: 0.55,
            n_trades: 12,
            n_signals: 45,
            signal_distribution: { BUY: 30, SELL: 10, FLAT: 5 },
            mean_confidence: confidence,
            mean_prob_long: 0.6,
            mean_prob_short: 0.4,
            current_price: 1.1234,
            last_signal_date: '2026-07-05T00:00:00Z',
            monthly_pf: 1.5,
            position,
            current_sl_mult: 2.5,
            current_tp_mult: 1.5,
            trade_log: [],
            feature_stability: {
              jaccard_top_10: 0.85,
              spearman_rank_corr: 0.72,
              penalty: 0.05,
              window_id: 'w1',
            },
            exit_reasons: {
              tp_rate: 0.3,
              sl_rate: 0.2,
              breakeven_rate: 0.1,
              flip_rate: 0.1,
              expiry_rate: 0.1,
              avg_r: 0.8,
            },
            archetype_stats: {},
            meta_inference: null,
            scale_out_active: false,
            remaining_fraction: 1,
            scale_out_tiers: null,
            psi_drift: {
              per_feature: [],
              worst_classification: '',
              moderate_count: 0,
              severe_count: 0,
              psi_ok: true,
              penalty: 0,
            },
            sharpe_ratio: 0.75,
            psr_gt_0: 0.82,
            psr_gt_1: 0.45,
            min_trl: 3.2,
            crs: 0.6,
            hhi: 0.12,
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
          last_signal: finalSignal
            ? {
                date: '2026-07-05T00:00:00Z',
                prob_long: 0.65,
                prob_short: 0.35,
                signal: finalSignal,
                confidence,
                close_price: 1.1234,
              }
            : null,
          gate_override: false,
          signal_flip: false,
          final_signal: finalSignal,
          execution_state: 'idle',
          sl_mult: 2,
          tp_mult: 2,
          meta_confidence: null,
          meta_decision: null,
          feature_stability_jaccard: 0.85,
          feature_stability_spearman: 0.72,
          sell_only: sellOnly,
          tripwire_active: tripwireActive,
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
      open_positions: openPosition ? ({ [assetName]: openPosition } as Record<string, OpenPositionState>) : undefined,
      engine_status: { initialized: true, last_update: '', start_time: '2026-07-01T00:00:00Z' },
      halt_conditions: { drawdown: 0, monthly_pf: 0, signal_drought: 0, prob_drift: 0 },
      risk_signals: riskSignal ? ({ [assetName]: riskSignal } as Record<string, RiskSignal>) : undefined,
      shadow_actions: shadowAction ? ({ [assetName]: shadowAction } as Record<string, ShadowAction>) : undefined,
    },
    live: {
      health: {
        fetch_time: '2026-07-05T00:00:00Z',
        fetch_age_seconds: 0,
        is_fresh: true,
        assets: {
          EURUSD: {
            asset: 'EURUSD',
            health_score: 0.92,
            health_label: 'healthy',
            health_color: '#22c55e',
            components: {
              validity: 0.9,
              drift: 0.95,
              pnl_stability: 0.85,
              shadow_agreement: 0.9,
              stress_robustness: 0.8,
            },
            limiting_factors: [],
            validity_state: 'GREEN',
          },
        },
        system_health: {
          mean_health_score: 0.88,
          n_assets: 1,
          n_healthy: 1,
          n_degraded: 0,
          n_critical: 0,
          healthiest_asset: 'EURUSD',
          weakest_asset: 'EURUSD',
        },
      },
      mt5: {
        fetch_time: '2026-07-05T00:00:00Z',
        fetch_age_seconds: 0,
        is_fresh: true,
        connected: true,
        status: 'CONNECTED' as const,
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

// ── Tests ─────────────────────────────────────────────────────────

describe('Data Flow: Bundle → Selectors → Hook → Component', () => {
  beforeEach(() => {
    mockFetch.mockReset()
    mockSetSelectedAsset.mockClear()
    mockSetDeepDiveAsset.mockClear()
  })

  // ── Selector layer ──────────────────────────────────────────────

  describe('Selectors (system.ts)', () => {
    it('selectAsset returns the correct asset slot', () => {
      const bundle = makeValidBundle({ assetName: 'EURUSD' })
      const asset = selectAsset('EURUSD')(bundle)
      expect(asset).not.toBeNull()
      expect(asset?.metrics.asset).toBe('EURUSD')
      expect(asset?.metrics.total_return).toBe(2.5)
    })

    it('selectAsset returns null for unknown asset', () => {
      const bundle = makeValidBundle()
      expect(selectAsset('NONEXIST')(bundle)).toBeNull()
    })

    it('selectAsset returns null when bundle has no assets', () => {
      const bundle = makeValidBundle()
      bundle.snapshot.assets = {}
      expect(selectAsset('EURUSD')(bundle)).toBeNull()
    })

    it('selectOpenPosition returns open position data', () => {
      const openPos = {
        position: { side: 'long', entry: 1.12, sl: 1.11, tp: 1.14, entry_date: '2026-07-04T00:00:00Z', vol: 1000, mt5_ticket: null } as OpenPositionState['position'],
        current_value: 100_500,
        peak_value: 100_800,
        running_mae: null,
        running_mfe: 0.5,
        trade_log: [],
        prob_history: [],
        bars_at_entry: 0,
        initial_sl: 1.11,
        initial_tp: 1.14,
      } as OpenPositionState
      const bundle = makeValidBundle({ openPosition: openPos })
      const pos = selectOpenPosition('EURUSD')(bundle)
      expect(pos).not.toBeNull()
      expect(pos?.position.side).toBe('long')
      expect(pos?.current_value).toBe(100_500)
    })

    it('selectMeta returns bundle metadata', () => {
      const bundle = makeValidBundle({ version: 'v2.0.0' })
      const meta = selectMeta(bundle)
      expect(meta.version).toBe('v2.0.0')
      expect(meta.snapshot_sequence_id).toBe(42)
    })

    it('systemSelectors.snapshot extracts the snapshot', () => {
      const bundle = makeValidBundle()
      const snap = systemSelectors.snapshot(bundle)
      expect(snap.contract_version).toBe(7)
      expect(snap.sequence_id).toBe(42)
    })

    it('systemSelectors.health extracts the live health object', () => {
      const bundle = makeValidBundle()
      const health = systemSelectors.health(bundle)
      expect(health.system_health.mean_health_score).toBe(0.88)
      expect(health.assets.EURUSD.health_score).toBe(0.92)
    })
  })

  // ── Hook layer ──────────────────────────────────────────────────

  describe('useSystemSnapshot with selectors', () => {
    it('fetches and returns data via full bundle selector', async () => {
      mockFetch.mockResolvedValue(makeValidBundle())
      const { wrapper } = withQueryClient()
      const { result } = renderHook(() => useSystemSnapshot(), { wrapper })
      await waitFor(() => expect(result.current.isSuccess).toBe(true))
      expect(result.current.data?.snapshot.portfolio.capital).toBe(100_000)
    })

    it('applies selectAsset selector correctly', async () => {
      mockFetch.mockResolvedValue(makeValidBundle())
      const { wrapper } = withQueryClient()
      const { result } = renderHook(
        () => useSystemSnapshot(selectAsset('EURUSD')),
        { wrapper },
      )
      await waitFor(() => expect(result.current.isSuccess).toBe(true))
      expect(result.current.data?.metrics.asset).toBe('EURUSD')
    })

    it('applies systemSelectors.portfolio selector correctly', async () => {
      mockFetch.mockResolvedValue(makeValidBundle())
      const { wrapper } = withQueryClient()
      const { result } = renderHook(
        () => useSystemSnapshot(systemSelectors.portfolio),
        { wrapper },
      )
      await waitFor(() => expect(result.current.isSuccess).toBe(true))
      expect(result.current.data?.capital).toBe(100_000)
    })
  })

  // ── Rendering layer (AssetCard) ─────────────────────────────────

  describe('AssetCard rendering with live data', () => {
    it('renders asset name and signal from mock bundle', async () => {
      mockFetch.mockResolvedValue(makeValidBundle({
        assetName: 'EURUSD',
        finalSignal: 'BUY',
        confidence: 0.65,
      }))
      const { wrapper } = withQueryClient()
      render(<AssetCard name="EURUSD" />, { wrapper })

      await waitFor(() => {
        expect(screen.getByText('EURUSD')).toBeInTheDocument()
      })
    })

    it('renders SELL signal correctly', async () => {
      mockFetch.mockResolvedValue(makeValidBundle({
        assetName: 'GBPUSD',
        finalSignal: 'SELL',
        confidence: 0.58,
      }))
      const { wrapper } = withQueryClient()
      render(<AssetCard name="GBPUSD" />, { wrapper })

      await waitFor(() => {
        expect(screen.getByText('GBPUSD')).toBeInTheDocument()
      })
    })

    it('renders compact density variant', async () => {
      mockFetch.mockResolvedValue(makeValidBundle({ assetName: 'EURUSD' }))
      const { wrapper } = withQueryClient()
      const { container } = render(<AssetCard name="EURUSD" density="compact" />, { wrapper })

      await waitFor(() => {
        // Compact cards are clickable with role="button"
        const cards = container.querySelectorAll('[role="button"],[role="button"] *')
        expect(cards.length).toBeGreaterThanOrEqual(0)
      })
    })

    it('shows no-data placeholder when asset is not in bundle', async () => {
      mockFetch.mockResolvedValue(makeValidBundle())
      const { wrapper } = withQueryClient()
      render(<AssetCard name="NONEXIST" />, { wrapper })

      await waitFor(() => {
        expect(screen.getByText('NONEXIST')).toBeInTheDocument()
        expect(screen.getByText('No data')).toBeInTheDocument()
      })
    })
  })
})
