import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import ExecutionQualityStrip from '../ExecutionQualityStrip'

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

describe('ExecutionQualityStrip', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAttributionBundle.mockReturnValue({
      data: { executionQuality: makeQualityData() },
      isPending: false,
    })
  })

  it('renders loading skeleton', () => {
    mockUseAttributionBundle.mockReturnValue({ data: null, isPending: true })
    renderWithQuery(<ExecutionQualityStrip />)
    expect(screen.getByText('Execution Quality')).toBeInTheDocument()
  })

  it('returns null when no assets', () => {
    mockUseAttributionBundle.mockReturnValue({
      data: { executionQuality: { by_asset: {} } },
      isPending: false,
    })
    const { container } = renderWithQuery(<ExecutionQualityStrip />)
    expect(container.innerHTML).toBe('')
  })

  it('renders four stat cells', () => {
    renderWithQuery(<ExecutionQualityStrip />)
    expect(screen.getByText('Avg EIS')).toBeInTheDocument()
    expect(screen.getByText('Avg FQI')).toBeInTheDocument()
    expect(screen.getByText('Worst Slippage')).toBeInTheDocument()
    expect(screen.getByText('Fill Rate')).toBeInTheDocument()
  })

  it('calculates and displays average EIS', () => {
    renderWithQuery(<ExecutionQualityStrip />)
    // EIS: (0.82 + 0.75) / 2 = 0.785 → 78.5%
    expect(screen.getByText('78.5%')).toBeInTheDocument()
  })

  it('calculates and displays average FQI', () => {
    renderWithQuery(<ExecutionQualityStrip />)
    // FQI: (0.91 + 0.85) / 2 = 0.88 → 88.0%
    expect(screen.getByText('88.0%')).toBeInTheDocument()
  })

  it('displays worst slippage', () => {
    renderWithQuery(<ExecutionQualityStrip />)
    // max(0.5, 1.2) = 1.2 bps
    expect(screen.getByText('1.2 bps')).toBeInTheDocument()
  })

  it('displays average fill rate', () => {
    renderWithQuery(<ExecutionQualityStrip />)
    // (0.98 + 0.95) / 2 = 0.965 → 96.5%
    expect(screen.getByText('96.5%')).toBeInTheDocument()
  })

  it('renders per-asset breakdown', () => {
    renderWithQuery(<ExecutionQualityStrip />)
    expect(screen.getByText('EURUSD')).toBeInTheDocument()
    expect(screen.getByText('GBPUSD')).toBeInTheDocument()
  })
})
