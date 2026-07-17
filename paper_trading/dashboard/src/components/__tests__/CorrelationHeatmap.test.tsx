import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import CorrelationHeatmap from '../CorrelationHeatmap'
import type { EquityHistoryPoint } from '../../hooks/useEquityHistory'

// ── pearsonCorrelation is a private module function, so we test it through
// the component's observable behavior. The math is verified by the empty-state
// threshold (n<3 → correlation treated as 0) and the warning-icon trigger (>0.7).
// For direct unit coverage we extract and re-export in the import below.
import { pearsonCorrelation } from '../CorrelationHeatmap'

const mockUseEquityHistory = vi.fn()

vi.mock('../../hooks/useEquityHistory', () => ({
  useEquityHistory: (...args: unknown[]) => mockUseEquityHistory(...args),
}))

vi.mock('../../hooks/useToast', () => ({
  useToast: () => ({ toast: vi.fn(), toasts: [], dismiss: vi.fn(), clear: vi.fn() }),
  ToastProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

function makeEquityPoint(
  timestamp: string,
  assets: Record<string, number>,
): EquityHistoryPoint {
  return {
    timestamp,
    portfolio_value: 100_000,
    portfolio_return: 0,
    drawdown: 0,
    gross_exposure: 0,
    net_exposure: 0,
    assets,
  }
}

function makeHistory(points: { timestamp: string; assets: Record<string, number> }[]): EquityHistoryPoint[] {
  return points.map(p => makeEquityPoint(p.timestamp, p.assets))
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

// ── pearsonCorrelation unit tests ──────────────────────────────────

describe('pearsonCorrelation', () => {
  it('returns 1 for perfect positive correlation', () => {
    expect(pearsonCorrelation([1, 2, 3], [2, 4, 6])).toBeCloseTo(1, 10)
  })

  it('returns -1 for perfect negative correlation', () => {
    expect(pearsonCorrelation([1, 2, 3], [6, 4, 2])).toBeCloseTo(-1, 10)
  })

  it('returns near 0 for uncorrelated data', () => {
    const x = [1, 2, 3, 4, 5]
    const y = [2, 2, 2, 2, 2]
    const r = pearsonCorrelation(x, y)
    expect(r).toBe(0)
  })

  it('returns 0 when denominator is 0 (constant series)', () => {
    expect(pearsonCorrelation([5, 5, 5], [1, 2, 3])).toBe(0)
    expect(pearsonCorrelation([1, 2, 3], [5, 5, 5])).toBe(0)
  })

  it('returns 0 when n < 3', () => {
    expect(pearsonCorrelation([1, 2], [3, 4])).toBe(0)
    expect(pearsonCorrelation([1], [2])).toBe(0)
    expect(pearsonCorrelation([], [])).toBe(0)
  })

  it('handles single-element arrays correctly', () => {
    expect(pearsonCorrelation([1], [2])).toBe(0)
  })

  it('handles floating-point precision correctly', () => {
    const x = [0.1, 0.2, 0.3, 0.4, 0.5]
    const y = [0.5, 0.4, 0.3, 0.2, 0.1]
    expect(pearsonCorrelation(x, y)).toBeCloseTo(-1, 10)
  })
})

// ── Component tests ────────────────────────────────────────────────

describe('CorrelationHeatmap', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders loading skeleton when data is pending', () => {
    mockUseEquityHistory.mockReturnValue({ data: null, isPending: true })
    const { container } = render(<CorrelationHeatmap />)
    expect(container.querySelector('.skeleton-shimmer')).toBeTruthy()
  })

  it('renders empty state when data is less than 10 points', () => {
    const history = makeHistory(
      Array.from({ length: 9 }, (_, i) => ({
        timestamp: `2026-07-${String(i + 1).padStart(2, '0')}T00:00:00Z`,
        assets: { EURUSD: 100_000 + i * 100 },
      })),
    )
    mockUseEquityHistory.mockReturnValue({ data: history, isPending: false })
    render(<CorrelationHeatmap />)
    expect(screen.getByText(/Need ≥10 data points/)).toBeInTheDocument()
  })

  it('renders empty state when data has fewer than 2 assets', () => {
    const history = makeHistory(
      Array.from({ length: 12 }, (_, i) => ({
        timestamp: `2026-07-${String(i + 1).padStart(2, '0')}T00:00:00Z`,
        assets: { EURUSD: 100_000 + i * 100 },
      })),
    )
    mockUseEquityHistory.mockReturnValue({ data: history, isPending: false })
    render(<CorrelationHeatmap />)
    expect(screen.getByText(/Insufficient asset history/)).toBeInTheDocument()
  })

  it('renders empty state when history is null', () => {
    mockUseEquityHistory.mockReturnValue({ data: null, isPending: false })
    render(<CorrelationHeatmap />)
    expect(screen.getByText(/Need ≥10 data points/)).toBeInTheDocument()
  })

  it('renders empty state when history is empty array', () => {
    mockUseEquityHistory.mockReturnValue({ data: [], isPending: false })
    render(<CorrelationHeatmap />)
    expect(screen.getByText(/Need ≥10 data points/)).toBeInTheDocument()
  })

  it('renders correlation table with correct asset rows', () => {
    const history = makeHistory(
      Array.from({ length: 12 }, (_, i) => ({
        timestamp: `2026-07-${String(i + 1).padStart(2, '0')}T00:00:00Z`,
        assets: {
          EURUSD: 100_000 + i * 100,
          GBPUSD: 200_000 + i * 50,
          USDJPY: 150_000 + i * 20,
          AUDUSD: 90_000 + i * 30,
        },
      })),
    )
    mockUseEquityHistory.mockReturnValue({ data: history, isPending: false })
    render(<CorrelationHeatmap />)
    // Asset names appear in both <th> (column headers) and <td> (row labels)
    expect(screen.getAllByText('EURUSD').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('GBPUSD').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('USDJPY').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('AUDUSD').length).toBeGreaterThanOrEqual(1)
  })

  it('displays asset count in section header', () => {
    const history = makeHistory(
      Array.from({ length: 12 }, (_, i) => ({
        timestamp: `2026-07-${String(i + 1).padStart(2, '0')}T00:00:00Z`,
        assets: {
          EURUSD: 100_000 + i * 100,
          GBPUSD: 200_000 + i * 50,
          USDJPY: 150_000 + i * 20,
        },
      })),
    )
    mockUseEquityHistory.mockReturnValue({ data: history, isPending: false })
    render(<CorrelationHeatmap />)
    expect(screen.getByText('3 assets')).toBeInTheDocument()
  })

  it('shows Show all button when 8 or more assets exist', () => {
    const assets: Record<string, number> = {}
    for (let i = 0; i < 10; i++) {
      assets[`ASSET${i}`] = 100_000 + i * 100
    }
    const history = makeHistory(
      Array.from({ length: 12 }, (_, i) => ({
        timestamp: `2026-07-${String(i + 1).padStart(2, '0')}T00:00:00Z`,
        assets,
      })),
    )
    mockUseEquityHistory.mockReturnValue({ data: history, isPending: false })
    render(<CorrelationHeatmap />)
    expect(screen.getByText(/Show all/)).toBeInTheDocument()
  })

  it('shows all assets after clicking Show all', () => {
    const assets: Record<string, number> = {}
    for (let i = 0; i < 10; i++) {
      assets[`ASSET${i}`] = 100_000 + i * 100
    }
    const history = makeHistory(
      Array.from({ length: 12 }, (_, i) => ({
        timestamp: `2026-07-${String(i + 1).padStart(2, '0')}T00:00:00Z`,
        assets,
      })),
    )
    mockUseEquityHistory.mockReturnValue({ data: history, isPending: false })
    render(<CorrelationHeatmap />)

    // Initially only 8/10 rows visible (slice(0, 8))
    expect(screen.getAllByText('ASSET0').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('ASSET7').length).toBeGreaterThanOrEqual(1)
    // ASSET8 and ASSET9 should NOT be visible until Show all is clicked
    expect(screen.queryAllByText('ASSET9').length).toBe(0)

    fireEvent.click(screen.getByText(/Show all/))
    expect(screen.getAllByText('ASSET9').length).toBeGreaterThanOrEqual(1)
  })

  it('toggles back to fewer assets on Show fewer', () => {
    const assets: Record<string, number> = {}
    for (let i = 0; i < 10; i++) {
      assets[`ASSET${i}`] = 100_000 + i * 100
    }
    const history = makeHistory(
      Array.from({ length: 12 }, (_, i) => ({
        timestamp: `2026-07-${String(i + 1).padStart(2, '0')}T00:00:00Z`,
        assets,
      })),
    )
    mockUseEquityHistory.mockReturnValue({ data: history, isPending: false })
    render(<CorrelationHeatmap />)
    fireEvent.click(screen.getByText(/Show all/))
    expect(screen.getAllByText('ASSET9').length).toBeGreaterThanOrEqual(1)

    fireEvent.click(screen.getByText(/Show fewer/))
    expect(screen.queryAllByText('ASSET9').length).toBe(0)
  })

  it('does not show Show all when fewer than 8 assets', () => {
    const history = makeHistory(
      Array.from({ length: 12 }, (_, i) => ({
        timestamp: `2026-07-${String(i + 1).padStart(2, '0')}T00:00:00Z`,
        assets: { EURUSD: 100_000 + i * 100, GBPUSD: 200_000 + i * 50 },
      })),
    )
    mockUseEquityHistory.mockReturnValue({ data: history, isPending: false })
    render(<CorrelationHeatmap />)
    expect(screen.queryByText(/Show all/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Show fewer/)).not.toBeInTheDocument()
  })

  it('shows warning icon for high correlation (>0.7)', () => {
    // Create two assets with near-identical values to force high correlation
    const base = 100_000
    const offset = 10
    const history = makeHistory(
      Array.from({ length: 12 }, (_, i) => ({
        timestamp: `2026-07-${String(i + 1).padStart(2, '0')}T00:00:00Z`,
        assets: {
          EURUSD: base + i * offset,
          GBPUSD: base + i * offset + 0.01,
        },
      })),
    )
    mockUseEquityHistory.mockReturnValue({ data: history, isPending: false })
    const { container } = render(<CorrelationHeatmap />)
    // The warning icon is a span with ⚠ character
    const warningIcons = container.querySelectorAll('[class*="ml-1"]')
    expect(warningIcons.length).toBeGreaterThanOrEqual(1)
  })

  it('shows section header with correct title', () => {
    const history = makeHistory(
      Array.from({ length: 12 }, (_, i) => ({
        timestamp: `2026-07-${String(i + 1).padStart(2, '0')}T00:00:00Z`,
        assets: { EURUSD: 100_000 + i * 100, GBPUSD: 200_000 + i * 50 },
      })),
    )
    mockUseEquityHistory.mockReturnValue({ data: history, isPending: false })
    render(<CorrelationHeatmap />)
    expect(screen.getByText('Correlation Matrix')).toBeInTheDocument()
  })
})
