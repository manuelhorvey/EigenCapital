import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import TradeFeed from '../TradeFeed'

// ── Mocks ─────────────────────────────────────────────────────────

const mockFetch = vi.fn()

vi.mock('../../lib/api', () => ({
  fetchApi: (...args: unknown[]) => mockFetch(...args),
}))

vi.mock('../trades/TradeInspectorModal', () => ({
  default: vi.fn(() => null),
}))

vi.mock('../../hooks/useSystemSnapshot', () => ({
  useSystemSnapshot: vi.fn((select?: (b: unknown) => unknown) => {
    const bundle = {
      snapshot: {
        engine_status: { start_time: '2026-07-01T00:00:00Z' },
        portfolio: { closed_trades: 5 },
        assets: {},
        timestamp: '2026-07-08T12:00:00Z',
        contract_version: 1,
        sequence_id: 1,
        schema_version: '1.0',
      },
    }
    if (!select) return { data: bundle, isPending: false, isError: false, error: null }
    return { data: select(bundle as never), isPending: false, isError: false, error: null }
  }),
}))

const mockTrades = [
  {
    asset: 'EURUSD',
    side: 'BUY',
    entry: 1.10500,
    exit: 1.10800,
    return: 0.0027,
    reason: 'tp',
    entry_date: '2026-07-07 14:00:00',
    exit_date: '2026-07-08 10:30:00',
    bars: 3,
  },
  {
    asset: 'GBPUSD',
    side: 'SELL',
    entry: 1.28500,
    exit: 1.28200,
    return: 0.0023,
    reason: 'sl',
    entry_date: '2026-07-08 06:00:00',
    exit_date: '2026-07-08 09:15:00',
    bars: 1.5,
  },
  {
    asset: 'AUDUSD',
    side: 'BUY',
    entry: 0.67500,
    exit: 0.66800,
    return: -0.0104,
    reason: 'signal_flip',
    entry_date: '2026-07-06 08:00:00',
    exit_date: '2026-07-07 16:45:00',
    bars: 4,
  },
]

function withQueryClient() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
  return { wrapper, queryClient }
}

// ── Tests ──────────────────────────────────────────────────────────

describe('TradeFeed', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows table skeleton when data is pending', () => {
    mockFetch.mockImplementation(() => new Promise(() => {})) // never resolves
    const { wrapper } = withQueryClient()
    const { container } = render(<TradeFeed />, { wrapper })
    expect(container.querySelector('.skeleton-shimmer')).toBeTruthy()
  })

  it('shows empty state with engine start date when no trades exist', async () => {
    mockFetch.mockResolvedValue([])
    const { wrapper } = withQueryClient()
    render(<TradeFeed />, { wrapper })

    // Should reference the engine start date
    expect(await screen.findByText(/engine started 2026-07-01/i)).toBeInTheDocument()
  })

  it('renders trade rows with BUY/SELL signal badges', async () => {
    mockFetch.mockResolvedValue(mockTrades)
    const { wrapper } = withQueryClient()
    render(<TradeFeed />, { wrapper })

    // Asset names appear in both mobile cards and desktop table — use getAllByText
    expect((await screen.findAllByText('EURUSD')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('GBPUSD').length).toBeGreaterThan(0)
    expect(screen.getAllByText('AUDUSD').length).toBeGreaterThan(0)

    // Signal badges — BUY/SELL appear in both mobile cards and desktop table
    expect(screen.getAllByText('BUY').length).toBeGreaterThan(0)
    expect(screen.getAllByText('SELL').length).toBeGreaterThan(0)
  })

  it('shows positive return in green and negative in red', async () => {
    mockFetch.mockResolvedValue(mockTrades)
    const { wrapper } = withQueryClient()
    const { container } = render(<TradeFeed />, { wrapper })

    // Wait for data to render
    await screen.findAllByText('EURUSD')

    // Positive return: +0.27% — first .text-gov-green has the return
    const greenElements = container.querySelectorAll('.text-gov-green')
    const hasPositiveReturn = Array.from(greenElements).some(el =>
      el.textContent?.includes('+0.27')
    )
    expect(hasPositiveReturn).toBe(true)

    // Negative return: -1.04% — first .text-gov-red has the return (not the SL badge)
    const redElements = container.querySelectorAll('.text-gov-red')
    const hasNegativeReturn = Array.from(redElements).some(el =>
      el.textContent?.includes('-1.04')
    )
    expect(hasNegativeReturn).toBe(true)
  })

  it('renders TP, SL, and FLIP reason badges', async () => {
    mockFetch.mockResolvedValue(mockTrades)
    const { wrapper } = withQueryClient()
    render(<TradeFeed />, { wrapper })

    // Wait for data, then check reason badges
    await screen.findAllByText('EURUSD')

    // Reason badges also appear in both mobile and desktop views
    expect(screen.getAllByText('TP').length).toBeGreaterThan(0)
    expect(screen.getAllByText('SL').length).toBeGreaterThan(0)
    expect(screen.getAllByText('FLIP').length).toBeGreaterThan(0)
  })

  it('shows held duration in days/hours format', async () => {
    mockFetch.mockResolvedValue(mockTrades)
    const { wrapper } = withQueryClient()
    const { container } = render(<TradeFeed />, { wrapper })

    await screen.findAllByText('EURUSD')

    // Check for duration-format strings (e.g. "3d", "1d 12h", etc.)
    const cells = container.querySelectorAll('.tabular-nums')
    const heldLabels = Array.from(cells).filter(el =>
      el.textContent?.includes('d') || el.textContent?.includes('h')
    )
    expect(heldLabels.length).toBeGreaterThan(0)
  })

  it('renders pagination controls with more trades than page size', async () => {
    // 11 trades to trigger pagination (PAGE_SIZE = 10)
    const manyTrades = Array.from({ length: 11 }, (_, i) => ({
      asset: `ASSET${i}`,
      side: i % 2 === 0 ? 'BUY' : 'SELL',
      entry: 1.0 + i * 0.01,
      exit: 1.0 + i * 0.02,
      return: i * 0.001,
      reason: i % 3 === 0 ? 'tp' : i % 3 === 1 ? 'sl' : 'flip',
      entry_date: `2026-07-0${(i % 7) + 1} 08:00:00`,
      exit_date: `2026-07-0${(i % 7) + 2} 10:00:00`,
      bars: i + 1,
    }))
    mockFetch.mockResolvedValue(manyTrades)
    const { wrapper } = withQueryClient()
    render(<TradeFeed />, { wrapper })

    // Should show pagination with a "next" button
    expect((await screen.findAllByText('ASSET0')).length).toBeGreaterThan(0)
    // Pagination button uses aria-label="Next page" with SVG icon — no visible text
    expect(screen.getByRole('button', { name: /next/i })).toBeInTheDocument()
  })

  it('handles empty string reason without crashing', async () => {
    const noReasonTrade = [{
      asset: 'NZDCAD',
      side: 'BUY',
      entry: 0.82000,
      exit: 0.82200,
      return: 0.0024,
      reason: '',
      entry_date: '2026-07-07 10:00:00',
      exit_date: '2026-07-08 12:00:00',
      bars: 2,
    }]
    mockFetch.mockResolvedValue(noReasonTrade)
    const { wrapper } = withQueryClient()
    const { container } = render(<TradeFeed />, { wrapper })

    expect((await screen.findAllByText('NZDCAD')).length).toBeGreaterThan(0)
    // Component renders without crashing with empty reason string
    expect(container.querySelector('table')).toBeInTheDocument()
  })
})
