import { describe, it, expect } from 'vitest'
import {
  PortfolioSummarySchema,
  EdgeHealthSummarySchema,
  PekPortfolioSnapshotSchema,
} from '../schemas'

describe('PortfolioSummarySchema — B1 / audit-fix-1.1', () => {
  describe('edge_health', () => {
    it('parses edge_health with all fields', () => {
      const result = PortfolioSummarySchema.safeParse({
        total_value: 100_000,
        total_return: 0.05,
        capital: 100_000,
        edge_health: {
          n_trades: 50,
          n_losers: 12,
          n_reversal_candidates: 6,
          reversal_rate: 0.5,
          warning_threshold: 0.15,
          alert: false,
          mean_mfe_r: 1.4,
          median_mfe_r: 1.2,
        },
      })
      expect(result.success).toBe(true)
      if (result.success) {
        expect(result.data.edge_health?.reversal_rate).toBe(0.5)
        expect(result.data.edge_health?.n_reversal_candidates).toBe(6)
      }
    })

    it('parses edge_health with null reversal_rate', () => {
      const result = PortfolioSummarySchema.safeParse({
        total_value: 100_000,
        total_return: 0.05,
        capital: 100_000,
        edge_health: {
          reversal_rate: null,
          n_losers: 0,
          n_trades: 0,
          mean_mfe_r: null,
          median_mfe_r: null,
          alert: false,
        },
      })
      expect(result.success).toBe(true)
      if (result.success) {
        expect(result.data.edge_health?.reversal_rate).toBe(null)
      }
    })

    it('omits edge_health gracefully', () => {
      const result = PortfolioSummarySchema.safeParse({
        total_value: 100_000,
        total_return: 0.05,
        capital: 100_000,
      })
      expect(result.success).toBe(true)
      if (result.success) {
        expect(result.data.edge_health).toBeUndefined()
      }
    })
  })

  describe('weekend_cycle', () => {
    it('captures boolean true', () => {
      const result = PortfolioSummarySchema.safeParse({
        total_value: 100_000,
        total_return: 0.05,
        capital: 100_000,
        weekend_cycle: true,
      })
      expect(result.success).toBe(true)
      if (result.success) {
        expect(result.data.weekend_cycle).toBe(true)
      }
    })
  })
})

describe('EdgeHealthSummarySchema', () => {
  it('permits but does not enforce non-negative counts (backend invariant)', () => {
    // The schema is permissive on negative counts by design — only field
    // *presence* matters for type safety. The backend's
    // `EdgeHealthMonitor.summary` invariant never emits negatives, but the
    // schema stays flexible to support historical fixtures.
    const result = EdgeHealthSummarySchema.safeParse({
      n_losers: -1,
      reversal_rate: 0.5,
      alert: false,
    })
    expect(result.success).toBe(true)
  })

  it('allows null reversal_rate', () => {
    const result = EdgeHealthSummarySchema.safeParse({
      reversal_rate: null,
      n_losers: 0,
      n_trades: 0,
      mean_mfe_r: null,
      median_mfe_r: null,
      alert: false,
    })
    expect(result.success).toBe(true)
  })
})

describe('PekPortfolioSnapshotSchema — daily_loss_remaining', () => {
  it('parses daily_loss_remaining', () => {
    const result = PekPortfolioSnapshotSchema.safeParse({
      total_equity: 100_000,
      drawdown_pct: -0.05,
      gross_exposure: 50_000,
      net_exposure: 0,
      open_position_count: 0,
      daily_pnl: -200,
      max_daily_loss: 2000,
      daily_loss_remaining: 1800,
      drawdown_remaining: 10_000,
      leverage_remaining: 150_000,
      max_leverage: 2,
      concurrent_remaining: 21,
      max_concurrent: 21,
    })
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data.daily_loss_remaining).toBe(1800)
    }
  })
})
