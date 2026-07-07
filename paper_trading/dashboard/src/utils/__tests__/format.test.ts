import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  formatAssetPrice,
  safeToFixed,
  clampPercent,
  confidenceToPercent,
  formatHeldDuration,
  formatTimeAgo,
  formatPct,
} from '../format'

describe('formatAssetPrice', () => {
  it('returns em-dash for null', () => {
    expect(formatAssetPrice(null)).toBe('—')
  })

  it('returns em-dash for undefined', () => {
    expect(formatAssetPrice(undefined)).toBe('—')
  })

  it('returns em-dash for NaN', () => {
    expect(formatAssetPrice(NaN)).toBe('—')
  })

  it('formats prices >= 10000 with 0 decimal places', () => {
    expect(formatAssetPrice(15000)).toBe('15,000')
    expect(formatAssetPrice(123456)).toBe('123,456')
  })

  it('formats prices >= 1000 with 2 decimal places', () => {
    expect(formatAssetPrice(1234.5678)).toBe('1,234.57')
    expect(formatAssetPrice(1000)).toBe('1,000.00')
  })

  it('formats prices >= 100 with 3 decimal places', () => {
    expect(formatAssetPrice(123.4567)).toBe('123.457')
    // 999.9999 < 1000 so dp=3, toLocaleString with 3dp rounds up → "1,000.000"
    expect(formatAssetPrice(999.9999)).toBe('1,000.000')
  })

  it('formats prices >= 1 with 4 decimal places (toLocaleString rounds 99.99999 to 100.0000)', () => {
    expect(formatAssetPrice(1.23456)).toBe('1.2346')
    // 99.99999 < 100 so dp=4, toLocaleString with 4dp rounds up → "100.0000"
    expect(formatAssetPrice(99.99999)).toBe('100.0000')
  })

  it('formats prices >= 0.01 with 5 decimal places', () => {
    expect(formatAssetPrice(0.12345)).toBe('0.12345')
    // 0.99999 >= 0.01 so dp=5, toLocaleString with 5dp keeps the value as-is
    expect(formatAssetPrice(0.99999)).toBe('0.99999')
  })

  it('formats prices < 0.01 with 6 decimal places', () => {
    expect(formatAssetPrice(0.001234)).toBe('0.001234')
    expect(formatAssetPrice(0.000001)).toBe('0.000001')
  })

  it('formats negative prices', () => {
    expect(formatAssetPrice(-15000)).toBe('-15,000')
    expect(formatAssetPrice(-1.23)).toBe('-1.2300')
  })

  it('formats zero', () => {
    expect(formatAssetPrice(0)).toBe('0.000000')
  })
})

describe('safeToFixed', () => {
  it('returns fallback for null', () => {
    expect(safeToFixed(null, 2)).toBe('—')
  })

  it('returns fallback for undefined', () => {
    expect(safeToFixed(undefined, 2)).toBe('—')
  })

  it('returns fallback for string', () => {
    expect(safeToFixed('hello', 2)).toBe('—')
  })

  it('returns fallback for Infinity', () => {
    expect(safeToFixed(Infinity, 2)).toBe('—')
  })

  it('returns fallback for -Infinity', () => {
    expect(safeToFixed(-Infinity, 2)).toBe('—')
  })

  it('formats a valid number', () => {
    expect(safeToFixed(3.14159, 2)).toBe('3.14')
  })

  it('uses custom fallback', () => {
    expect(safeToFixed(null, 2, 'N/A')).toBe('N/A')
  })

  it('handles negative numbers', () => {
    expect(safeToFixed(-1.5, 0)).toBe('-2')
  })
})

describe('clampPercent', () => {
  it('returns 0 for null', () => {
    expect(clampPercent(null)).toBe(0)
  })

  it('returns 0 for undefined', () => {
    expect(clampPercent(undefined)).toBe(0)
  })

  it('returns 0 for NaN', () => {
    expect(clampPercent(NaN)).toBe(0)
  })

  it('returns 0 for Infinity', () => {
    expect(clampPercent(Infinity)).toBe(0)
  })

  it('clamps negative values to 0', () => {
    expect(clampPercent(-10)).toBe(0)
  })

  it('clamps values above 100 to 100', () => {
    expect(clampPercent(150)).toBe(100)
  })

  it('passes through values in [0, 100]', () => {
    expect(clampPercent(0)).toBe(0)
    expect(clampPercent(50)).toBe(50)
    expect(clampPercent(100)).toBe(100)
  })
})

describe('confidenceToPercent', () => {
  it('returns 0 for null', () => {
    expect(confidenceToPercent(null)).toBe(0)
  })

  it('returns 0 for undefined', () => {
    expect(confidenceToPercent(undefined)).toBe(0)
  })

  it('multiplies decimals (0-1 range) by 100', () => {
    expect(confidenceToPercent(0.5)).toBe(50)
    expect(confidenceToPercent(0.75)).toBe(75)
    expect(confidenceToPercent(1)).toBe(100)
  })

  it('passes through values already in percent range', () => {
    expect(confidenceToPercent(50)).toBe(50)
    expect(confidenceToPercent(75)).toBe(75)
  })

  it('clamps to [0, 100]', () => {
    expect(confidenceToPercent(-0.5)).toBe(0)
    // 1.5 > 1 → treated as already in percent range → clamped to [0,100] = 1.5
    expect(confidenceToPercent(1.5)).toBe(1.5)
    // 200 > 1 → treated as already in percent range → clamped to [0,100] = 100
    expect(confidenceToPercent(200)).toBe(100)
  })

  it('handles edge case of 0', () => {
    expect(confidenceToPercent(0)).toBe(0)
  })
})

describe('formatHeldDuration', () => {
  it('returns em-dash for null', () => {
    expect(formatHeldDuration(null)).toBe('—')
  })

  it('returns em-dash for undefined', () => {
    expect(formatHeldDuration(undefined)).toBe('—')
  })

  it('returns em-dash for negative values', () => {
    expect(formatHeldDuration(-1)).toBe('—')
  })

  it('returns "<1d" for values less than 1', () => {
    expect(formatHeldDuration(0)).toBe('<1d')
    expect(formatHeldDuration(0.5)).toBe('<1d')
  })

  it('formats whole days', () => {
    expect(formatHeldDuration(1)).toBe('1d')
    expect(formatHeldDuration(5)).toBe('5d')
  })

  it('formats days and hours', () => {
    expect(formatHeldDuration(1.5)).toBe('1d 12h')
    expect(formatHeldDuration(2.25)).toBe('2d 6h')
  })

  it('returns <1d for values between 0 and 1 (fractional bars)', () => {
    // Values between 0 and 1 hit the `bars < 1` guard before the days/hours logic.
    expect(formatHeldDuration(0.75)).toBe('<1d')
    expect(formatHeldDuration(0.1)).toBe('<1d')
  })

  it('handles exactly 1 bar as 1d when hours is 0', () => {
    expect(formatHeldDuration(1)).toBe('1d')
  })
})

describe('formatTimeAgo', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-07T12:00:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns "just now" for < 5 seconds ago', () => {
    const now = new Date('2026-07-07T11:59:58Z')
    expect(formatTimeAgo(now.toISOString())).toBe('just now')
  })

  it('returns "Xs ago" for < 60 seconds', () => {
    const thirtySecAgo = new Date('2026-07-07T11:59:30Z')
    expect(formatTimeAgo(thirtySecAgo.toISOString())).toBe('30s ago')
  })

  it('returns "Xm ago" for < 60 minutes', () => {
    const fiveMinAgo = new Date('2026-07-07T11:55:00Z')
    expect(formatTimeAgo(fiveMinAgo.toISOString())).toBe('5m ago')
  })

  it('returns "Xh ago" for < 24 hours', () => {
    const threeHoursAgo = new Date('2026-07-07T09:00:00Z')
    expect(formatTimeAgo(threeHoursAgo.toISOString())).toBe('3h ago')
  })

  it('returns "Xd ago" for >= 24 hours', () => {
    const twoDaysAgo = new Date('2026-07-05T12:00:00Z')
    expect(formatTimeAgo(twoDaysAgo.toISOString())).toBe('2d ago')
  })

  it('returns "unknown" for invalid date string', () => {
    expect(formatTimeAgo('not-a-date')).toBe('unknown')
  })
})

describe('formatPct', () => {
  it('returns em-dash for null', () => {
    expect(formatPct(null)).toBe('—')
  })

  it('returns em-dash for undefined', () => {
    expect(formatPct(undefined)).toBe('—')
  })

  it('returns em-dash for Infinity', () => {
    expect(formatPct(Infinity)).toBe('—')
  })

  it('prepends + for positive values', () => {
    expect(formatPct(5.123)).toBe('+5.12%')
  })

  it('prepends nothing for negative values', () => {
    expect(formatPct(-3.456)).toBe('-3.46%')
  })

  it('handles zero', () => {
    expect(formatPct(0)).toBe('+0.00%')
  })

  it('uses custom digits', () => {
    expect(formatPct(7.12345, 3)).toBe('+7.123%')
  })
})
