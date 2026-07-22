import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useGovernanceRadar } from '../useGovernanceRadar'

// ── Mocks ─────────────────────────────────────────────────────────

type SnapshotData = Record<string, unknown>

function makeDefaultSnapshot(): SnapshotData {
  return {
    sequence_id: 1,
    portfolio: { average_validity_exposure: 0.9 },
    assets: {
      EURUSD: {
        metrics: { asset: 'EURUSD', drawdown: -0.05 },
        feature_stability_jaccard: 0.85,
        meta_confidence: 0.75,
        validity_state: 'LONG',
      },
      GBPUSD: {
        metrics: { asset: 'GBPUSD', drawdown: -0.03 },
        feature_stability_jaccard: 0.9,
        meta_confidence: 0.8,
        validity_state: 'LONG',
      },
    },
    halt_conditions: { drawdown: -0.08, prob_drift: 0.1 },
  }
}

function makeDefaultHealth(): SnapshotData {
  return {
    assets: {
      EURUSD: { health_score: 0.88 },
      GBPUSD: { health_score: 0.92 },
    },
  }
}

let mockSnapshot = makeDefaultSnapshot()
let mockHealth = makeDefaultHealth()

vi.mock('../useSystemSnapshot', () => ({
  useSystemSnapshot: vi.fn((select?: (b: unknown) => unknown) => {
    const bundle = {
      snapshot: mockSnapshot,
      live: { health: mockHealth },
    }
    if (!select) return { data: bundle, isPending: false }
    return { data: select(bundle as never), isPending: false }
  }),
}))

// ── Tests ──────────────────────────────────────────────────────────

describe('useGovernanceRadar', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSnapshot = makeDefaultSnapshot()
    mockHealth = makeDefaultHealth()
  })

  it('returns 6 radar axes with correct labels', () => {
    const { result } = renderHook(() => useGovernanceRadar())
    const labels = result.current.axes.map(a => a.label)
    expect(labels).toEqual([
      'Exposure',
      'Feature Stability',
      'Meta-Label',
      'Health',
      'PSI Drift',
      'Drawdown Control',
    ])
  })

  it('computes exposure score from average_validity_exposure', () => {
    mockSnapshot = {
      ...makeDefaultSnapshot(),
      portfolio: { average_validity_exposure: 0.5 },
    }
    const { result } = renderHook(() => useGovernanceRadar())
    const exposure = result.current.axes.find(a => a.label === 'Exposure')
    expect(exposure!.value).toBeCloseTo(0.5, 1)
  })

  it('computes feature stability as mean Jaccard across assets', () => {
    const { result } = renderHook(() => useGovernanceRadar())
    const feat = result.current.axes.find(a => a.label === 'Feature Stability')
    // (0.85 + 0.9) / 2 = 0.875
    expect(feat!.value).toBeCloseTo(0.875, 2)
  })

  it('computes health score from health data', () => {
    const { result } = renderHook(() => useGovernanceRadar())
    const health = result.current.axes.find(a => a.label === 'Health')
    // (0.88 + 0.92) / 2 = 0.9
    expect(health!.value).toBeCloseTo(0.9, 1)
  })

  it('computes PSI drift score inversely from prob_drift', () => {
    mockSnapshot = {
      ...makeDefaultSnapshot(),
      halt_conditions: { drawdown: -0.08, prob_drift: 0.4 },
    }
    const { result } = renderHook(() => useGovernanceRadar())
    const psi = result.current.axes.find(a => a.label === 'PSI Drift')
    // psiScore = max(0, 1 - 0.4 * 2) = max(0, 1 - 0.9) = 0.2
    expect(psi!.value).toBeCloseTo(0.2, 1)
  })

  it('creates PSI Drift bottleneck when drift > 0.2', () => {
    mockSnapshot = {
      ...makeDefaultSnapshot(),
      halt_conditions: { drawdown: -0.08, prob_drift: 0.5 },
      assets: {
        EURUSD: {
          metrics: { asset: 'EURUSD', drawdown: -0.05 },
          feature_stability_jaccard: 0.85,
          meta_confidence: 0.75,
          validity_state: 'HALTED',
        },
      },
    }
    const { result } = renderHook(() => useGovernanceRadar())
    const psiBottleneck = result.current.bottlenecks.find(b => b.layer === 'PSI Drift')
    expect(psiBottleneck).toBeDefined()
    expect(psiBottleneck!.assets).toContain('EURUSD')
  })

  it('creates Exposure bottleneck when avg exposure < 0.85', () => {
    mockSnapshot = {
      ...makeDefaultSnapshot(),
      portfolio: { average_validity_exposure: 0.6 },
    }
    const { result } = renderHook(() => useGovernanceRadar())
    const expBottleneck = result.current.bottlenecks.find(b => b.layer === 'Exposure')
    expect(expBottleneck).toBeDefined()
    expect(expBottleneck!.assets).toContain('SYSTEM')
  })

  it('creates Health bottleneck when avg health < 0.8', () => {
    mockHealth = {
      assets: {
        EURUSD: { health_score: 0.5 },
        GBPUSD: { health_score: 0.92 },
      },
    }
    const { result } = renderHook(() => useGovernanceRadar())
    const healthBottleneck = result.current.bottlenecks.find(b => b.layer === 'System Health')
    expect(healthBottleneck).toBeDefined()
    expect(healthBottleneck!.assets).toContain('EURUSD')
  })

  it('creates Drawdown bottleneck when drawdown usage > 75%', () => {
    // portfolio_drawdown is a fraction; the formula multiplies by 100 for comparison.
    // | -0.08 * 100 | / | (-0.08 * 100) | = 8 / 8 = 1.0 (100%) > 0.75
    mockSnapshot = {
      ...makeDefaultSnapshot(),
      portfolio: { average_validity_exposure: 0.9, portfolio_drawdown: -0.08 },
      assets: {
        EURUSD: {
          metrics: { asset: 'EURUSD', drawdown: -0.05 },
          feature_stability_jaccard: 0.85,
          meta_confidence: 0.75,
          validity_state: 'LONG',
        },
      },
      halt_conditions: { drawdown: -0.08, prob_drift: 0.1 },
    }
    const { result } = renderHook(() => useGovernanceRadar())
    const ddBottleneck = result.current.bottlenecks.find(b => b.layer === 'Drawdown')
    expect(ddBottleneck).toBeDefined()
  })

  it('returns empty bottlenecks for a healthy system', () => {
    const { result } = renderHook(() => useGovernanceRadar())
    expect(result.current.bottlenecks).toHaveLength(0)
  })

  it('returns fallback axis values when no snapshot data', () => {
    mockSnapshot = {} as never
    mockHealth = {} as never
    const { result } = renderHook(() => useGovernanceRadar())
    // Each axis has its own fallback logic — check individually
    expect(result.current.axes.find(a => a.label === 'Exposure')!.value).toBe(0)
    expect(result.current.axes.find(a => a.label === 'Feature Stability')!.value).toBe(0.5)
    expect(result.current.axes.find(a => a.label === 'Meta-Label')!.value).toBe(0.5)
    expect(result.current.axes.find(a => a.label === 'Health')!.value).toBe(0.5)
    expect(result.current.axes.find(a => a.label === 'PSI Drift')!.value).toBe(1)
    expect(result.current.axes.find(a => a.label === 'Drawdown Control')!.value).toBe(1)
  })

  it('returns non-negative avgValidityImpact', () => {
    const { result } = renderHook(() => useGovernanceRadar())
    expect(result.current.avgValidityImpact).toBeGreaterThanOrEqual(0)
  })

  it('includes description in each radar axis', () => {
    const { result } = renderHook(() => useGovernanceRadar())
    result.current.axes.forEach(axis => {
      expect(axis.description).toBeTruthy()
      expect(axis.max).toBe(1)
    })
  })

  it('sorts bottlenecks by penalty ascending', () => {
    // Trigger multiple bottlenecks
    mockSnapshot = {
      ...makeDefaultSnapshot(),
      portfolio: { average_validity_exposure: 0.4 },
      halt_conditions: { drawdown: -0.08, prob_drift: 0.5 },
      assets: {
        EURUSD: {
          metrics: { asset: 'EURUSD', drawdown: -0.08 },
          feature_stability_jaccard: 0.85,
          meta_confidence: 0.75,
          validity_state: 'HALTED',
        },
      },
    }
    mockHealth = {
      assets: {
        EURUSD: { health_score: 0.5 },
        GBPUSD: { health_score: 0.3 },
      },
    }
    const { result } = renderHook(() => useGovernanceRadar())
    const penalties = result.current.bottlenecks.map(b => b.avgPenalty)
    for (let i = 1; i < penalties.length; i++) {
      expect(penalties[i]).toBeGreaterThanOrEqual(penalties[i - 1])
    }
  })


})
