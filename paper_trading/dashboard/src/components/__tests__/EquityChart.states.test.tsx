import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import EquityChart from '../EquityChart'

const mockUseEquityHistory = vi.fn()
const mockUseSystemSnapshot = vi.fn()

vi.mock('../../hooks/useEquityHistory', () => ({
  useEquityHistory: () => mockUseEquityHistory(),
}))

vi.mock('../../hooks/useSystemSnapshot', () => ({
  useSystemSnapshot: (select?: (b: unknown) => unknown) => {
    const bundle = {
      snapshot: {
        portfolio: { capital: 100_000 },
      },
    }
    if (!select) return mockUseSystemSnapshot()
    return { data: select(bundle as never), isPending: false }
  },
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

describe('EquityChart — empty state', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseSystemSnapshot.mockReturnValue({ data: null, isPending: false, isError: false })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows empty state when equity history is empty', async () => {
    mockUseEquityHistory.mockReturnValue({ data: [], isPending: false })

    const { wrapper } = withQueryClient()
    render(<EquityChart />, { wrapper })

    // Should show the empty state message from ChartContainer
    const emptyMessage = await screen.findByText('Waiting for equity history\u2026')
    expect(emptyMessage).toBeInTheDocument()
  })

  it('shows loading skeleton when data is pending', async () => {
    mockUseEquityHistory.mockReturnValue({ data: undefined, isPending: true })

    const { wrapper } = withQueryClient()
    const { container } = render(<EquityChart />, { wrapper })

    // Should show skeleton while loading
    const skeletons = container.querySelectorAll('.skeleton, .skeleton-shimmer')
    expect(skeletons.length).toBeGreaterThan(0)
  })
})
