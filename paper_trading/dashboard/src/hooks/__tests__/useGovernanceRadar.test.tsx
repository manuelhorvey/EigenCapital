import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useGovernanceRadar } from '../useGovernanceRadar'

vi.mock('../useSystemSnapshot', () => ({
  useSystemSnapshot: vi.fn(),
}))

import { useSystemSnapshot } from '../useSystemSnapshot'

const BASE_PORTFOLIO = {
  average_validity_exposure: 1, total_value: 100_000, capital: 100_000,
  allocations: {}, open_positions: 0, closed_trades: 0,
}

const BASE_HALT = { drawdown: -0.08, prob_drift: 0 }

const HEALTHY_ASSETS: Record<string, unknown> = {
  EURUSD: {
    asset: 'EURUSD', health_score: 0.92, health_label: 'healthy', health_color: 'green',
    components: { validity: 0.9, drift: 0.85, pnl_stability: 0.95, shadow_agreement: 0.88, stress_robustness: 0.9 },
    limiting_factors: [], validity_state: 'LONG',
  },
  GBPUSD: {
    asset: 'GBPUSD', health_score: 0.88, health_label: 'healthy', health_color: 'green',
    components: { validity: 0.85, drift: 0.8, pnl_stability: 0.9, shadow_agreement: 0.85, stress_robustness: 0.88 },
    limiting_factors: [], validity_state: 'LONG',
  },
}

function mockSnapshot(overrides: Record<string, unknown> = {}) {
  const mock = vi.mocked(useSystemSnapshot)
  const data = {
    contract_version: 7,
    sequence_id: 1,
    portfolio: { ...BASE_PORTFOLIO, ...(overrides.portfolio as object || {}) },
    assets: { ...HEALTHY_ASSETS, ...(overrides.assets as object || {}) },
    halt_conditions: { ...BASE_HALT, ...(overrides.halt_conditions as object || {}) },
    engine_status: { initialized: true, last_update: '', start_time: '' },
  }
  mock.mockReturnValue({ data, isPending: false, isError: false, error: null, isSuccess: true } as ReturnType<typeof useSystemSnapshot>)
}

describe('useGovernanceRadar', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('returns 6 axes with valid ranges', () => {
    mockSnapshot()
    const { result } = renderHook(() => useGovernanceRadar())
    expect(result.current.axes.length).toBe(6)
    expect(result.current.axes.every(a => a.value >= 0 && a.value <= 1)).toBe(true)
    expect(result.current.axes.map(a => a.label)).toEqual([
      'Exposure', 'Feature Stability', 'Meta-Label', 'Health', 'PSI Drift', 'Drawdown Control',
    ])
  })

  it('lowers exposure score when portfolio has low validity exposure', () => {
    mockSnapshot({
      portfolio: { ...BASE_PORTFOLIO, average_validity_exposure: 0.4 },
    })
    const { result } = renderHook(() => useGovernanceRadar())
    const exposure = result.current.axes.find(a => a.label === 'Exposure')
    expect(exposure!.value).toBe(0.4)
  })

  it('detects PSI drift bottleneck when prob_drift > 0.2', () => {
    mockSnapshot({
      halt_conditions: { ...BASE_HALT, prob_drift: 0.5 },
    })
    const { result } = renderHook(() => useGovernanceRadar())
    expect(result.current.bottlenecks.length).toBeGreaterThanOrEqual(1)
    expect(result.current.bottlenecks.some(b => b.layer === 'PSI Drift')).toBe(true)
  })

  it('detects drawdown bottleneck when drawdown usage > 75%', () => {
    mockSnapshot({
      portfolio: { ...BASE_PORTFOLIO, portfolio_drawdown: -0.0007 },
      halt_conditions: { ...BASE_HALT, drawdown: -0.0008 },
    })
    const { result } = renderHook(() => useGovernanceRadar())
    // drawdownUsage = | -0.0007 * 100 | / | -0.0008 * 100 | = 0.07 / 0.08 = 0.875 > 0.75
    expect(result.current.bottlenecks.some(b => b.layer === 'Drawdown')).toBe(true)
  })

  it('returns empty bottlenecks when all scores are healthy', () => {
    mockSnapshot({ assets: {} })
    const { result } = renderHook(() => useGovernanceRadar())
    expect(result.current.bottlenecks).toHaveLength(0)
  })

  it('returns avgValidityImpact consistent with bottlenecks', () => {
    mockSnapshot({
      halt_conditions: { ...BASE_HALT, prob_drift: 0.5 },
    })
    const { result } = renderHook(() => useGovernanceRadar())
    expect(result.current.bottlenecks.length).toBeGreaterThan(0)
    expect(typeof result.current.avgValidityImpact).toBe('number')
    expect(result.current.avgValidityImpact).toBeLessThanOrEqual(0)
  })
})
