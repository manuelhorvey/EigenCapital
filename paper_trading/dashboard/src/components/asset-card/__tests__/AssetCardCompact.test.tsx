import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import AssetCardCompact from '../AssetCardCompact'
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

describe('AssetCardCompact', () => {
  const onSelect = vi.fn()

  it('renders asset name and signal', () => {
    render(<AssetCardCompact name="EURUSD" info={baseInfo} onSelect={onSelect} />)
    expect(screen.getByText('EURUSD')).toBeInTheDocument()
    expect(screen.getByText('BUY')).toBeInTheDocument()
    expect(screen.getByText('75%')).toBeInTheDocument()
  })

  it('renders price and return values', () => {
    render(<AssetCardCompact name="EURUSD" info={baseInfo} onSelect={onSelect} />)
    expect(screen.getByText(/\$150\.25/)).toBeInTheDocument()
    expect(screen.getByText('+3.5%')).toBeInTheDocument()
  })

  it('shows drawdown and trade count', () => {
    render(<AssetCardCompact name="EURUSD" info={baseInfo} onSelect={onSelect} />)
    expect(screen.getByText(/DD -2\.1%/)).toBeInTheDocument()
    expect(screen.getByText('12tr')).toBeInTheDocument()
  })

  it('shows SELL signal with correct styling class', () => {
    const sellInfo = { ...baseInfo, signal: 'SELL', confidence: 60 }
    const { container } = render(<AssetCardCompact name="GBPUSD" info={sellInfo} onSelect={onSelect} />)
    expect(container.querySelector('.border-l-signal-short')).toBeTruthy()
  })

  it('shows FLAT signal with gray styling', () => {
    const flatInfo = { ...baseInfo, signal: 'FLAT', confidence: 50 }
    const { container } = render(<AssetCardCompact name="USDJPY" info={flatInfo} onSelect={onSelect} />)
    expect(container.querySelector('.border-l-signal-gray')).toBeTruthy()
  })

  it('shows tripwire badge when tripwireActive is true', () => {
    const tripInfo = { ...baseInfo, tripwireActive: true }
    render(<AssetCardCompact name="EURUSD" info={tripInfo} onSelect={onSelect} />)
    expect(screen.getByText('⚠')).toBeInTheDocument()
  })

  it('shows SO badge when sellOnly is true', () => {
    const soInfo = { ...baseInfo, sellOnly: true }
    render(<AssetCardCompact name="EURAUD" info={soInfo} onSelect={onSelect} />)
    expect(screen.getByText('SO')).toBeInTheDocument()
  })

  it('shows position SL and TP when position exists', () => {
    const posInfo = {
      ...baseInfo,
      position: { entry: 1.05, side: 'long' as const, sl: 1.02, tp: 1.10 },
      risk: { tpDistPct: 4.76, slDistPct: -2.86, rr: 1.67 },
    }
    render(<AssetCardCompact name="EURUSD" info={posInfo} onSelect={onSelect} />)
    expect(screen.getByText(/1\.02/)).toBeInTheDocument()
    expect(screen.getByText(/1\.10/)).toBeInTheDocument()
  })

  it('hides position SL/TP when no position', () => {
    const { container } = render(<AssetCardCompact name="EURUSD" info={baseInfo} onSelect={onSelect} />)
    // The SL/TP row only renders when info.position exists
    expect(container.textContent).not.toMatch(/^SL/)
  })

  it('calls onSelect when clicked', () => {
    render(<AssetCardCompact name="EURUSD" info={baseInfo} onSelect={onSelect} />)
    screen.getByRole('button').click()
    expect(onSelect).toHaveBeenCalledTimes(1)
  })

  it('uses compact price format for sub-10 assets', () => {
    const lowPriceInfo = { ...baseInfo, price: 1.05 }
    const { container } = render(<AssetCardCompact name="EURUSD" info={lowPriceInfo} onSelect={onSelect} />)
    // For price < 10, toFixed(5) is used — expect 5 decimal places
    expect(container.textContent).toMatch(/1\.05000/)
  })
})
