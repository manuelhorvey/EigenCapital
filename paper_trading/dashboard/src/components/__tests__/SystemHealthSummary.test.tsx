import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import SystemHealthSummary from '../SystemHealthSummary'
import type { PortfolioTradingState } from '../../lib/trading-state/types'

// Mock useTradingState
vi.mock('../../lib/trading-state/hook', () => ({
  useTradingState: vi.fn(),
}))

import { useTradingState } from '../../lib/trading-state/hook'

const mockPortfolio: PortfolioTradingState = {
  system_status: 'SAFE',
  pnl: { total: 0.05, efficiency: 0.6 },
  risk: { drawdown: 0.02, net_exposure: 0.1, concentration_risk: 'LOW' },
  execution: { mt5_sync: 'HEALTHY', sl_sync_integrity: 'OK' },
  alpha: { reversal_rate: 0.2, edge_trend: 'STABLE' },
  alerts: [],
  top_3_risks: [],
  recent_events: [],
}

const negativePortfolio: PortfolioTradingState = {
  system_status: 'SAFE',
  pnl: { total: -0.03, efficiency: 0.4 },
  risk: { drawdown: 0.08, net_exposure: -0.2, concentration_risk: 'MEDIUM' },
  execution: { mt5_sync: 'DEGRADED', sl_sync_integrity: 'WARNING' },
  alpha: { reversal_rate: null, edge_trend: 'DECAYING' },
  alerts: ['System degraded', 'Drawdown elevated'],
  top_3_risks: [
    { title: 'Drawdown pressure high', severity: 'HIGH' },
  ],
  recent_events: [],
}

const mockUseTradingState = vi.mocked(useTradingState)

describe('SystemHealthSummary', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows loading skeleton when isLoading is true', () => {
    mockUseTradingState.mockReturnValue({
      portfolio: null as unknown as PortfolioTradingState,
      assets: {},
      assetList: [],
      sortKey: 'risk',
      sortAsc: false,
      setSortKey: vi.fn(),
      toggleSortDirection: vi.fn(),
      isLoading: true,
      isError: false,
    })

    const { container } = render(<SystemHealthSummary />)
    // Should render skeleton elements (shimmer class)
    expect(container.querySelector('.skeleton-shimmer')).toBeTruthy()
  })

  it('shows loading skeleton when portfolio is null', () => {
    mockUseTradingState.mockReturnValue({
      portfolio: null as unknown as PortfolioTradingState,
      assets: {},
      assetList: [],
      sortKey: 'risk',
      sortAsc: false,
      setSortKey: vi.fn(),
      toggleSortDirection: vi.fn(),
      isLoading: false,
      isError: false,
    })

    const { container } = render(<SystemHealthSummary />)
    expect(container.querySelector('.skeleton-shimmer')).toBeTruthy()
  })

  it('renders SAFE badge when system is healthy', () => {
    mockUseTradingState.mockReturnValue({
      portfolio: mockPortfolio,
      assets: {},
      assetList: [],
      sortKey: 'risk',
      sortAsc: false,
      setSortKey: vi.fn(),
      toggleSortDirection: vi.fn(),
      isLoading: false,
      isError: false,
    })

    render(<SystemHealthSummary />)
    expect(screen.getByText('SAFE')).toBeInTheDocument()
    expect(screen.getByText('All systems nominal')).toBeInTheDocument()
  })

  it('renders PnL value correctly for positive total', () => {
    mockUseTradingState.mockReturnValue({
      portfolio: mockPortfolio,
      assets: {},
      assetList: [],
      sortKey: 'risk',
      sortAsc: false,
      setSortKey: vi.fn(),
      toggleSortDirection: vi.fn(),
      isLoading: false,
      isError: false,
    })

    render(<SystemHealthSummary />)

    // PnL = +0.05% (backend sends percentage values as-is)
    expect(screen.getByText('+0.05%')).toBeInTheDocument()
    // Efficiency = 60% (0.6 * 100)
    expect(screen.getByText('Eff: 60%')).toBeInTheDocument()
  })

  it('renders PnL value with negative sign for negative total', () => {
    mockUseTradingState.mockReturnValue({
      portfolio: negativePortfolio,
      assets: {},
      assetList: [],
      sortKey: 'risk',
      sortAsc: false,
      setSortKey: vi.fn(),
      toggleSortDirection: vi.fn(),
      isLoading: false,
      isError: false,
    })

    render(<SystemHealthSummary />)
    // PnL = -0.03% (backend sends percentage values as-is)
    expect(screen.getByText('-0.03%')).toBeInTheDocument()
  })

  it('uses CSS variable references for PnL accent color', () => {
    mockUseTradingState.mockReturnValue({
      portfolio: mockPortfolio,
      assets: {},
      assetList: [],
      sortKey: 'risk',
      sortAsc: false,
      setSortKey: vi.fn(),
      toggleSortDirection: vi.fn(),
      isLoading: false,
      isError: false,
    })

    const { container } = render(<SystemHealthSummary />)
    const html = container.innerHTML

    // When PnL is positive (0.05 >= 0), accent should be var(--color-gov-green)
    expect(html).toContain('var(--color-gov-green)')

    // When MT5 sync is HEALTHY, accent should be var(--color-gov-green)
    expect(html).toContain('var(--color-gov-green)')
  })

  it('uses CSS variable references for negative PnL', () => {
    mockUseTradingState.mockReturnValue({
      portfolio: negativePortfolio,
      assets: {},
      assetList: [],
      sortKey: 'risk',
      sortAsc: false,
      setSortKey: vi.fn(),
      toggleSortDirection: vi.fn(),
      isLoading: false,
      isError: false,
    })

    const { container } = render(<SystemHealthSummary />)
    const html = container.innerHTML

    // When PnL is negative (-0.03 < 0), accent should be var(--color-gov-red)
    expect(html).toContain('var(--color-gov-red)')

    // When MT5 sync is DEGRADED, accent should be var(--color-gov-yellow)
    expect(html).toContain('var(--color-gov-yellow)')
  })

  it('shows alert message when alerts exist', () => {
    mockUseTradingState.mockReturnValue({
      portfolio: negativePortfolio,
      assets: {},
      assetList: [],
      sortKey: 'risk',
      sortAsc: false,
      setSortKey: vi.fn(),
      toggleSortDirection: vi.fn(),
      isLoading: false,
      isError: false,
    })

    render(<SystemHealthSummary />)
    expect(screen.getByText('System degraded')).toBeInTheDocument()
    expect(screen.getByText('+1 more')).toBeInTheDocument()
  })

  it('shows top risks when present', () => {
    mockUseTradingState.mockReturnValue({
      portfolio: negativePortfolio,
      assets: {},
      assetList: [],
      sortKey: 'risk',
      sortAsc: false,
      setSortKey: vi.fn(),
      toggleSortDirection: vi.fn(),
      isLoading: false,
      isError: false,
    })

    render(<SystemHealthSummary />)
    expect(screen.getByText('Drawdown pressure high')).toBeInTheDocument()
  })

  it('renders Edge Health with "No data" when reversal_rate is null', () => {
    mockUseTradingState.mockReturnValue({
      portfolio: negativePortfolio,
      assets: {},
      assetList: [],
      sortKey: 'risk',
      sortAsc: false,
      setSortKey: vi.fn(),
      toggleSortDirection: vi.fn(),
      isLoading: false,
      isError: false,
    })

    render(<SystemHealthSummary />)
    expect(screen.getByText('No data')).toBeInTheDocument()
  })

  it('renders reversal rate when available', () => {
    const withReversal = {
      ...mockPortfolio,
      alpha: { reversal_rate: 0.35, edge_trend: 'EXPANDING' as const },
    }
    mockUseTradingState.mockReturnValue({
      portfolio: withReversal,
      assets: {},
      assetList: [],
      sortKey: 'risk',
      sortAsc: false,
      setSortKey: vi.fn(),
      toggleSortDirection: vi.fn(),
      isLoading: false,
      isError: false,
    })

    render(<SystemHealthSummary />)
    // Reversal rate = 35%
    expect(screen.getByText('Rev: 35%')).toBeInTheDocument()
  })
})
