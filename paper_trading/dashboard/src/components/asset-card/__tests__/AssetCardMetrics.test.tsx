import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import AssetCardMetrics from '../AssetCardMetrics'
import type { AssetCardInfo } from '../types'

const baseInfo: AssetCardInfo = {
  signal: 'BUY',
  confidence: 75,
  price: 150.25,
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
}

describe('AssetCardMetrics', () => {
  it('renders total return with sign', () => {
    render(<AssetCardMetrics info={baseInfo} />)
    expect(screen.getByText('+3.50%')).toBeInTheDocument()
  })

  it('renders negative return correctly', () => {
    const negInfo = { ...baseInfo, totalReturn: -5.2 }
    render(<AssetCardMetrics info={negInfo} />)
    const el = screen.getByText('-5.20%')
    expect(el).toBeInTheDocument()
    expect(el.className).toContain('signal-short')
  })

  it('renders drawdown', () => {
    render(<AssetCardMetrics info={baseInfo} />)
    expect(screen.getByText(/DD -2\.10%/)).toBeInTheDocument()
  })

  it('renders mean confidence', () => {
    render(<AssetCardMetrics info={baseInfo} />)
    expect(screen.getByText(/Conf 70\.0%/)).toBeInTheDocument()
  })

  it('renders SL and TP multipliers', () => {
    render(<AssetCardMetrics info={baseInfo} />)
    expect(screen.getByText('2.50x')).toBeInTheDocument()
    expect(screen.getByText('1.50x')).toBeInTheDocument()
  })

  it('renders signal distribution counts', () => {
    render(<AssetCardMetrics info={baseInfo} />)
    expect(screen.getByText(/30B/)).toBeInTheDocument()
    expect(screen.getByText(/10S/)).toBeInTheDocument()
    expect(screen.getByText(/5F/)).toBeInTheDocument()
  })

  it('renders signals and trades count', () => {
    render(<AssetCardMetrics info={baseInfo} />)
    expect(screen.getByText(/45 sigs/)).toBeInTheDocument()
    expect(screen.getByText(/12 trades/)).toBeInTheDocument()
  })

  it('does not render multiplier row when slMult/tpMult are null', () => {
    const nullMultipliers = { ...baseInfo, slMult: null, tpMult: null }
    const view = render(<AssetCardMetrics info={nullMultipliers} />)
    // Should not contain "SL" label or multiplier values
    expect(view.container.textContent).not.toMatch(/SL|TP/)
  })

  it('handles empty signal distribution', () => {
    const empty = { ...baseInfo, signalDistribution: undefined, slMult: null, tpMult: null }
    render(<AssetCardMetrics info={empty} />)
    expect(screen.getByText('+3.50%')).toBeInTheDocument()
  })
})
