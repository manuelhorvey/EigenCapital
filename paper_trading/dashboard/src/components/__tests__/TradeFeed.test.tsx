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

    // Asset names should be visible
    expect(await screen.findByText('EURUSD')).toBeInTheDocument()
    expect(screen.getByText('GBPUSD')).toBeInTheDocument()
    expect(screen.getByText('AUDUSD')).toBeInTheDocument()

    // Signal badges — note TradeFeed passes side as children, and
    // Badge renders uppercase; BUY becomes "BUY", SELL becomes "SELL"
    expect(screen.getByText('BUY')).toBeInTheDocument()
    expect(screen.getByText('SELL')).toBeInTheDocument()
  })

  it('shows positive return in green and negative in red', async () => {
    mockFetch.mockResolvedValue(mockTrades)
    const { wrapper } = withQueryClient()
    const { container } = render(<TradeFeed />, { wrapper })

    // Wait for data to render
    await screen.findByText('EURUSD')

    // Positive return: +0.27%
    const positiveReturns = container.querySelector('.text-gov-green')
    expect(positiveReturns?.textContent).toContain('+0.27')

    // Negative return: -1.04%
    const negativeReturns = container.querySelector('.text-gov-red')
    expect(negativeReturns?.textContent).toContain('-1.04')
  })

  it('renders TP, SL, and FLIP reason badges', async () => {
    mockFetch.mockResolvedValue(mockTrades)
    const { wrapper } = withQueryClient()
    render(<TradeFeed />, { wrapper })

    // Wait for data, then check reason badges
    await screen.findByText('EURUSD')

    // Badge text is the mapped reason label
    expect(screen.getByText('TP')).toBeInTheDocument()
    expect(screen.getByText('SL')).toBeInTheDocument()
    expect(screen.getByText('FLIP')).toBeInTheDocument()
  })

  it('shows held duration in days/hours format', async () => {
    mockFetch.mockResolvedValue(mockTrades)
    const { wrapper } = withQueryClient()
    const { container } = render(<TradeFeed />, { wrapper })

    await screen.findByText('EURUSD')

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
    await screen.findByText('ASSET0')
    expect(screen.getByText(/next/i)).toBeInTheDocument()
  })

  it('shows dash for missing exit reason', async () => {
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
    render(<TradeFeed />, { wrapper })

    await screen.findByText('NZDCAD')
    // Unknown/missing reasons show '—'
    expect(screen.getByText('—')).toBeInTheDocument()
  })
})
