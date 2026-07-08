import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useGovernanceRadar } from '../useGovernanceRadar'

// Mock useSystemSnapshot at the module level to return controlled data
// without going through fetchApi or schema validation.
vi.mock('../useSystemSnapshot', () => ({
  useSystemSnapshot: vi.fn(),
}))

import { useSystemSnapshot } from '../useSystemSnapshot'

function mockSnapshot(overrides: Record<string, unknown> = {}) {
  const mock = vi.mocked(useSystemSnapshot)
  mock.mockImplementation(() => {
    const bundle = {
      snapshot: {
        contract_version: 7,
        sequence_id: 1,
        portfolio: {
          average_validity_exposure: 1,
          total_value: 100_000,
          capital: 100_000,
          allocations: {},
          open_positions: 0,
          closed_trades: 0,
        },
        assets: {},
        halt_conditions: { drawdown: -0.08, prob_drift: 0 },
        ...overrides,
      },
      live: {
        health: {
          assets: {
            EURUSD: { asset: 'EURUSD', health_score: 0.92, health_label: 'healthy', health_color: 'green' },
            GBPUSD: { asset: 'GBPUSD', health_score: 0.88, health_label: 'healthy', health_color: 'green' },
          },
        },
      },
    }
    // Return type-compatible shape: `useQuery` result
    return { data: bundle, isPending: false, isError: false, error: null, isSuccess: true } as ReturnType<typeof useSystemSnapshot>
  })
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
      portfolio: { average_validity_exposure: 0.4, total_value: 100_000, capital: 100_000, allocations: {}, open_positions: 0, closed_trades: 0 },
    })
    const { result } = renderHook(() => useGovernanceRadar())
    const exposure = result.current.axes.find(a => a.label === 'Exposure')
    expect(exposure!.value).toBe(0.4)
  })

  it('detects PSI drift bottleneck when prob_drift > 0.2', () => {
    mockSnapshot({
      halt_conditions: { drawdown: -0.08, prob_drift: 0.5 },
      assets: {},
    })
    const { result } = renderHook(() => useGovernanceRadar())
    expect(result.current.bottlenecks.length).toBeGreaterThanOrEqual(1)
    expect(result.current.bottlenecks.some(b => b.layer === 'PSI Drift')).toBe(true)
  })

  it('detects drawdown bottleneck when drawdown usage > 75%', () => {
    // drawdownLimitPct = Math.abs(-0.0008 * 100) = 0.08
    // drawdownUsage = Math.abs(-0.07) / 0.08 = 0.875 > 0.75
    mockSnapshot({
      assets: {
        EURUSD: {
          metrics: {
            asset: 'EURUSD', drawdown: -0.07, current_value: 100_000, settled_value: 100_000, mtm_value: 100_000,
            total_return: 0, settled_return: 0, mtm_return: 0,
          },
        },
      },
      halt_conditions: { drawdown: -0.0008, prob_drift: 0 },
    })
    const { result } = renderHook(() => useGovernanceRadar())
    expect(result.current.bottlenecks.some(b => b.layer === 'Drawdown')).toBe(true)
  })

  it('returns empty bottlenecks when all scores are healthy', () => {
    mockSnapshot({ assets: {} })
    const { result } = renderHook(() => useGovernanceRadar())
    expect(result.current.bottlenecks).toHaveLength(0)
  })

  it('returns avgValidityImpact consistent with bottlenecks', () => {
    mockSnapshot({
      halt_conditions: { drawdown: -0.08, prob_drift: 0.5 },
    })
    const { result } = renderHook(() => useGovernanceRadar())
    expect(result.current.bottlenecks.length).toBeGreaterThan(0)
    expect(typeof result.current.avgValidityImpact).toBe('number')
    expect(result.current.avgValidityImpact).toBeLessThanOrEqual(0)
  })
})
