import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import AttributionBreakdownCard from '../AttributionBreakdownCard'

// ── Mock useAttributionBundle ──────────────────────────────────────────

const mockUseAttributionBundle = vi.fn()

vi.mock('../../../hooks/useAttributionBundle', () => ({
  useAttributionBundle: (...args: unknown[]) => mockUseAttributionBundle(...args),
}))

function makeBundle(overrides?: Partial<ReturnType<typeof mockUseAttributionBundle>>) {
  return {
    data: {
      attributionSummary: {
        overall: {
          n_trades: 42,
          avg_r: 0.65,
          avg_mae_pct: 0.3,
          avg_mfe_pct: 1.2,
          domain_scores: {
            prediction_score: 0.75,
            execution_score: 0.82,
            exit_score: 0.65,
            friction_score: 0.90,
          },
        },
        by_archetype: {},
        by_regime: {},
        domain_scores: {},
      },
      executionQuality: null,
      executionSlippage: null,
      attributionWaterfall: null,
    },
    isPending: false,
    ...overrides,
  }
}

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('AttributionBreakdownCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAttributionBundle.mockReturnValue(makeBundle())
  })

  it('renders loading skeleton when pending', () => {
    mockUseAttributionBundle.mockReturnValue({ data: null, isPending: true })
    renderWithQuery(<AttributionBreakdownCard />)
    expect(screen.getByText('Attribution Breakdown')).toBeInTheDocument()
    // Should have skeleton elements
    const skeletons = document.querySelectorAll('.skeleton-shimmer, .skeleton')
    expect(skeletons.length).toBeGreaterThan(0)
  })

  it('returns null when no domain scores available', () => {
    mockUseAttributionBundle.mockReturnValue({
      data: { attributionSummary: { overall: { domain_scores: null } } },
      isPending: false,
    })
    const { container } = renderWithQuery(<AttributionBreakdownCard />)
    expect(container.innerHTML).toBe('')
  })

  it('renders four domain score KPIs', () => {
    renderWithQuery(<AttributionBreakdownCard />)
    expect(screen.getByText('Attribution Breakdown')).toBeInTheDocument()
    expect(screen.getByText(/Prediction/)).toBeInTheDocument()
    expect(screen.getByText(/Execution/)).toBeInTheDocument()
    expect(screen.getByText(/Exit/)).toBeInTheDocument()
    expect(screen.getByText(/Friction/)).toBeInTheDocument()
  })

  it('shows formatted percentage values', () => {
    renderWithQuery(<AttributionBreakdownCard />)
    expect(screen.getByText('75%')).toBeInTheDocument()
    expect(screen.getByText('82%')).toBeInTheDocument()
    expect(screen.getByText('65%')).toBeInTheDocument()
    expect(screen.getByText('90%')).toBeInTheDocument()
  })

  it('shows trade count in header', () => {
    renderWithQuery(<AttributionBreakdownCard />)
    expect(screen.getByText('42 trades')).toBeInTheDocument()
  })

  it('renders per-archetype breakdown when available', () => {
    mockUseAttributionBundle.mockReturnValue({
      data: {
        attributionSummary: {
          overall: {
            n_trades: 10,
            domain_scores: { prediction_score: 0.6, execution_score: 0.7, exit_score: 0.5, friction_score: 0.8 },
          },
          domain_scores: {
            MOMENTUM: { prediction_score: 0.8, execution_score: 0.9, exit_score: 0.7, friction_score: 0.95 },
          },
        },
      },
      isPending: false,
    })
    renderWithQuery(<AttributionBreakdownCard />)
    expect(screen.getByText('MOMENTUM')).toBeInTheDocument()
  })

  it('does not show by-archetype section when domain_scores is empty', () => {
    renderWithQuery(<AttributionBreakdownCard />)
    expect(screen.queryByText('By Archetype')).not.toBeInTheDocument()
  })
})
