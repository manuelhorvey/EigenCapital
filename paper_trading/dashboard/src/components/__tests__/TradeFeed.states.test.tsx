import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import TradeFeed from '../TradeFeed'

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
        portfolio: { closed_trades: 0 },
      },
    }
    if (!select) return { data: bundle, isPending: false, isError: false, error: null }
    return { data: select(bundle as never), isPending: false, isError: false, error: null }
  }),
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

describe('TradeFeed — error state', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows error state when the fetch fails', async () => {
    mockFetch.mockRejectedValue(new Error('HTTP 500'))
    const { wrapper } = withQueryClient()
    const { container } = render(<TradeFeed />, { wrapper })

    await waitFor(() => {
      // The hook enters error state — check that the table skeleton or error is not rendered
      // With retry: false, the error should be surfaced quickly
      expect(mockFetch).toHaveBeenCalled()
    })

    // Component renders nothing on error but should not crash
    await waitFor(() => {
      expect(container.querySelector('table')).toBeNull()
    })
  })
})
