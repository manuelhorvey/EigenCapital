import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import AssetCardPosition from '../AssetCardPosition'
import type { AssetCardInfo } from '../types'

const baseInfo: AssetCardInfo = {
  signal: 'BUY',
  confidence: 75,
  price: 1.1050,
  totalReturn: 3.5,
  drawdown: -2.1,
  meanConfidence: 70,
  nTrades: 12,
  nSignals: 45,
  position: undefined,
  risk: null,
  signalDistribution: { BUY: 30, SELL: 10, FLAT: 5 },
  sellOnly: false,
  tripwireActive: false,
  slMult: 2.5,
  tpMult: 1.5,
  scaleOutActive: false,
  scaleOutTiers: null,
  remainingFraction: 1,
  isNew: false,
  riskSignal: null,
  shadowAction: null,
  priceHistory: null,
  positionEntry: null,
  positionTp: null,
  positionSl: null,
  positionSide: null,
}

describe('AssetCardPosition', () => {
  it('returns null when no position', () => {
    const { container } = render(<AssetCardPosition info={baseInfo} />)
    expect(container.innerHTML).toBe('')
  })

  it('renders position side and entry price', () => {
    const info: AssetCardInfo = {
      ...baseInfo,
      position: { entry: 1.1000, side: 'long', sl: 1.0950, tp: 1.1100 },
      risk: { tpDistPct: 0.91, slDistPct: -0.45, rr: 2.0 },
    }
    render(<AssetCardPosition info={info} />)
    expect(screen.getByText(/LONG/)).toBeInTheDocument()
    expect(screen.getByText(/\$1\.1000/)).toBeInTheDocument()
  })

  it('renders short position with red dot', () => {
    const info: AssetCardInfo = {
      ...baseInfo,
      position: { entry: 1.1000, side: 'short', sl: 1.1050, tp: 1.0900 },
      risk: { tpDistPct: -0.91, slDistPct: 0.45, rr: 2.0 },
    }
    const { container } = render(<AssetCardPosition info={info} />)
    expect(screen.getByText(/SHORT/)).toBeInTheDocument()
    expect(container.innerHTML).toContain('gov-red')
  })

  it('renders unrealized PnL when present', () => {
    const info: AssetCardInfo = {
      ...baseInfo,
      position: { entry: 1.1000, side: 'long', sl: 1.0950, tp: 1.1100, unrealized_pnl: 25.50 },
      risk: { tpDistPct: 0.91, slDistPct: -0.45, rr: 2.0 },
    }
    render(<AssetCardPosition info={info} />)
    expect(screen.getByText(/\+25\.50 uPnL/)).toBeInTheDocument()
  })

  it('renders negative unrealized PnL in red', () => {
    const info: AssetCardInfo = {
      ...baseInfo,
      position: { entry: 1.1000, side: 'long', sl: 1.0950, tp: 1.1100, unrealized_pnl: -10.00 },
      risk: { tpDistPct: 0.91, slDistPct: -0.45, rr: 2.0 },
    }
    const { container } = render(<AssetCardPosition info={info} />)
    expect(screen.getByText(/-10\.00 uPnL/)).toBeInTheDocument()
    expect(container.innerHTML).toContain('gov-red')
  })

  it('renders TP and SL distances with percentages', () => {
    const info: AssetCardInfo = {
      ...baseInfo,
      position: { entry: 1.1000, side: 'long', sl: 1.0950, tp: 1.1100 },
      risk: { tpDistPct: 0.91, slDistPct: -0.45, rr: 2.0 },
    }
    render(<AssetCardPosition info={info} />)
    expect(screen.getByText(/↑0\.91%/)).toBeInTheDocument()
    expect(screen.getByText(/↓-0\.45%/)).toBeInTheDocument()
  })

  it('renders risk/reward ratio', () => {
    const info: AssetCardInfo = {
      ...baseInfo,
      position: { entry: 1.1000, side: 'long', sl: 1.0950, tp: 1.1100 },
      risk: { tpDistPct: 0.91, slDistPct: -0.45, rr: 2.0 },
    }
    render(<AssetCardPosition info={info} />)
    expect(screen.getByText(/2\.0:1/)).toBeInTheDocument()
  })

  it('renders scale-out tiers when active', () => {
    const info: AssetCardInfo = {
      ...baseInfo,
      position: { entry: 1.1000, side: 'long', sl: 1.0950, tp: 1.1100, unrealized_pnl: 50 },
      risk: { tpDistPct: 0.91, slDistPct: -0.45, rr: 2.0 },
      scaleOutActive: true,
      scaleOutTiers: [
        { fraction: 0.6, price: 1.1050, filled: true, fill_price: 1.1050 },
        { fraction: 0.4, price: 1.1100, filled: false },
      ],
      remainingFraction: 0.4,
    }
    render(<AssetCardPosition info={info} />)
    expect(screen.getByText('Scale-out tiers')).toBeInTheDocument()
    expect(screen.getByText(/40% remain/)).toBeInTheDocument()
    expect(screen.getByText('60%')).toBeInTheDocument()  // first tier filled, unique fraction
  })

  it('does not render scale-out section when inactive', () => {
    const info: AssetCardInfo = {
      ...baseInfo,
      position: { entry: 1.1000, side: 'long', sl: 1.0950, tp: 1.1100 },
      risk: { tpDistPct: 0.91, slDistPct: -0.45, rr: 2.0 },
      scaleOutActive: false,
      scaleOutTiers: [{ fraction: 0.5, price: 1.1050, filled: true, fill_price: 1.1050 }],
      remainingFraction: 0.5,
    }
    const { container } = render(<AssetCardPosition info={info} />)
    expect(container.textContent).not.toMatch(/Scale-out/)
  })

  it('shows layer count badge when multiple layers', () => {
    const info: AssetCardInfo = {
      ...baseInfo,
      position: {
        entry: 1.1000,
        side: 'long',
        sl: 1.0950,
        tp: 1.1100,
        layers: [{ entry_price: 1.1000, size: 0.5, timestamp: '2026-01-01', signal_id: 'a', pnl_at_time: 0 }],
      },
      risk: { tpDistPct: 0.91, slDistPct: -0.45, rr: 2.0 },
    }
    // Layers array has only 1 element, so length === 1, badge won't show
    render(<AssetCardPosition info={info} />)
    expect(screen.getByText(/LONG/)).toBeInTheDocument()
    // Should NOT show ×1 badge since length <= 1
    expect(screen.queryByText(/×1/)).not.toBeInTheDocument()
  })

  it('shows ×N badge when 2+ layers', () => {
    const info: AssetCardInfo = {
      ...baseInfo,
      position: {
        entry: 1.1000,
        side: 'long',
        sl: 1.0950,
        tp: 1.1100,
        layers: [{ entry_price: 1.10, size: 0.3, timestamp: 'a', signal_id: 'a', pnl_at_time: 0 },
                 { entry_price: 1.10, size: 0.3, timestamp: 'b', signal_id: 'b', pnl_at_time: 0 }],
      },
      risk: { tpDistPct: 0.91, slDistPct: -0.45, rr: 2.0 },
    }
    render(<AssetCardPosition info={info} />)
    expect(screen.getByText(/×2/)).toBeInTheDocument()
  })

  it('renders price sparkline when priceHistory has 4+ samples', () => {
    const prices = [1.0995, 1.1000, 1.1010, 1.1025, 1.1040, 1.1055]
    const info: AssetCardInfo = {
      ...baseInfo,
      position: { entry: 1.1000, side: 'long', sl: 1.0950, tp: 1.1100, unrealized_pnl: 5.5 },
      risk: { tpDistPct: 0.91, slDistPct: -0.45, rr: 2.0 },
      priceHistory: prices,
      positionEntry: 1.1000,
      positionTp: 1.1100,
      positionSl: 1.0950,
      positionSide: 'long',
    }
    const { container } = render(<AssetCardPosition info={info} />)
    const svg = container.querySelector('svg')
    expect(svg).not.toBeNull()
    expect(container.querySelector('path')).not.toBeNull()
  })

  it('omits sparkline when fewer than 4 samples (too noisy to be useful)', () => {
    const info: AssetCardInfo = {
      ...baseInfo,
      position: { entry: 1.1000, side: 'long', sl: 1.0950, tp: 1.1100 },
      risk: { tpDistPct: 0.91, slDistPct: -0.45, rr: 2.0 },
      priceHistory: [1.1000, 1.1005, 1.1010],
      positionEntry: 1.1000,
      positionTp: 1.1100,
      positionSl: 1.0950,
      positionSide: 'long',
    }
    const { container } = render(<AssetCardPosition info={info} />)
    expect(container.querySelector('svg')).toBeNull()
  })

  it('omits sparkline when no priceHistory provided', () => {
    const info: AssetCardInfo = {
      ...baseInfo,
      position: { entry: 1.1000, side: 'long', sl: 1.0950, tp: 1.1100 },
      risk: { tpDistPct: 0.91, slDistPct: -0.45, rr: 2.0 },
      priceHistory: null,
      positionEntry: 1.1000,
      positionTp: 1.1100,
      positionSl: 1.0950,
      positionSide: 'long',
    }
    const { container } = render(<AssetCardPosition info={info} />)
    expect(container.querySelector('svg')).toBeNull()
  })

  it('renders short sparkline without crashing on flat prices', () => {
    const info: AssetCardInfo = {
      ...baseInfo,
      position: { entry: 1.1000, side: 'short', sl: 1.1050, tp: 1.0900 },
      risk: { tpDistPct: -0.91, slDistPct: 0.45, rr: 2.0 },
      priceHistory: [1.1000, 1.1000, 1.1000, 1.1000, 1.1000],
      positionEntry: 1.1000,
      positionTp: 1.0900,
      positionSl: 1.1050,
      positionSide: 'short',
    }
    const { container } = render(<AssetCardPosition info={info} />)
    const svg = container.querySelector('svg')
    expect(svg).not.toBeNull()
    expect(container.querySelector('path')).not.toBeNull()
  })
})
