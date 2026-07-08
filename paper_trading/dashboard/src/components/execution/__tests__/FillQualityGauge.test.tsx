import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import FillQualityGauge from '../FillQualityGauge'

const mockUseAttributionBundle = vi.fn()

vi.mock('../../../hooks/useAttributionBundle', () => ({
  useAttributionBundle: (...args: unknown[]) => mockUseAttributionBundle(...args),
}))

function makeQualityData() {
  return {
    by_asset: {
      EURUSD: { eis: 0.82, fqi: 0.91, avg_entry_slippage_bps: 0.5, avg_exit_slippage_bps: 0.3, avg_latency_bars: 0, gap_rate: 0, partial_fill_rate: 0, avg_fill_ratio: 0.98, n: 5 },
      GBPUSD: { eis: 0.75, fqi: 0.85, avg_entry_slippage_bps: 1.2, avg_exit_slippage_bps: 0.8, avg_latency_bars: 1, gap_rate: 0.05, partial_fill_rate: 0.02, avg_fill_ratio: 0.95, n: 3 },
    },
  }
}

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('FillQualityGauge', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAttributionBundle.mockReturnValue({
      data: { executionQuality: makeQualityData() },
      isPending: false,
    })
  })

  it('renders loading skeleton', () => {
    mockUseAttributionBundle.mockReturnValue({ data: null, isPending: true })
    renderWithQuery(<FillQualityGauge />)
    expect(screen.getByText('Fill Quality')).toBeInTheDocument()
  })

  it('returns null when no assets', () => {
    mockUseAttributionBundle.mockReturnValue({
      data: { executionQuality: { by_asset: {} } },
      isPending: false,
    })
    const { container } = renderWithQuery(<FillQualityGauge />)
    expect(container.innerHTML).toBe('')
  })

  it('renders empty state when no FQI or EIS data', () => {
    mockUseAttributionBundle.mockReturnValue({
      data: { executionQuality: { by_asset: { EURUSD: { eis: null, fqi: null, avg_entry_slippage_bps: 0, avg_exit_slippage_bps: 0, avg_latency_bars: 0, gap_rate: 0, partial_fill_rate: 0, avg_fill_ratio: 0.98, n: 0 } } } },
      isPending: false,
    })
    renderWithQuery(<FillQualityGauge />)
    expect(screen.getByText('Waiting for execution data\u2026')).toBeInTheDocument()
  })

  it('renders gauge components for FQI and Fill Ratio', () => {
    renderWithQuery(<FillQualityGauge />)
    expect(screen.getByText('Avg FQI')).toBeInTheDocument()
    expect(screen.getByText('Fill Ratio')).toBeInTheDocument()
  })

  it('displays per-asset FQI breakdown', () => {
    renderWithQuery(<FillQualityGauge />)
    expect(screen.getByText('EURUSD')).toBeInTheDocument()
    expect(screen.getByText('GBPUSD')).toBeInTheDocument()
  })

  it('shows FQI values in per-asset list', () => {
    renderWithQuery(<FillQualityGauge />)
    expect(screen.getByText('FQI=91%')).toBeInTheDocument()
    expect(screen.getByText('FQI=85%')).toBeInTheDocument()
  })
})
