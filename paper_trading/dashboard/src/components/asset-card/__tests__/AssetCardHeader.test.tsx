import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import AssetCardHeader from '../AssetCardHeader'
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

describe('AssetCardHeader', () => {
  it('renders asset name and signal', () => {
    render(
      <AssetCardHeader
        name="EURUSD"
        info={baseInfo}
        cardState="GREEN"
        confidenceState="GREEN"
        badge={null}
      />,
    )
    expect(screen.getByText('EURUSD')).toBeInTheDocument()
    expect(screen.getByText('BUY')).toBeInTheDocument()
    expect(screen.getByText('75%')).toBeInTheDocument()
  })

  it('renders price when present', () => {
    render(
      <AssetCardHeader
        name="EURUSD"
        info={baseInfo}
        cardState="GREEN"
        confidenceState="GREEN"
        badge={null}
      />,
    )
    expect(screen.getByText(/\$150\.25/)).toBeInTheDocument()
  })

  it('does not render price when null', () => {
    const noPriceInfo = { ...baseInfo, price: null }
    const { container } = render(
      <AssetCardHeader
        name="EURUSD"
        info={noPriceInfo}
        cardState="GREEN"
        confidenceState="GREEN"
        badge={null}
      />,
    )
    expect(container.textContent).not.toMatch(/\$/)
  })

  it('renders yellow badge with correct label', () => {
    render(
      <AssetCardHeader
        name="EURUSD"
        info={baseInfo}
        cardState="GREEN"
        confidenceState="GREEN"
        badge={{ label: 'SELL_ONLY', tone: 'yellow', pulse: false }}
      />,
    )
    const badge = screen.getByText('SELL_ONLY')
    expect(badge).toBeInTheDocument()
    expect(badge.className).toContain('signal-warn')
  })

  it('renders red badge with pulse animation', () => {
    render(
      <AssetCardHeader
        name="EURUSD"
        info={baseInfo}
        cardState="GREEN"
        confidenceState="GREEN"
        badge={{ label: 'TRIPWIRE', tone: 'red', pulse: true }}
      />,
    )
    const badge = screen.getByText('TRIPWIRE')
    expect(badge).toBeInTheDocument()
    expect(badge.className).toContain('signal-short')
    expect(badge.className).toContain('animate-pulse')
  })

  it('does not render badge when null', () => {
    const { container } = render(
      <AssetCardHeader
        name="EURUSD"
        info={baseInfo}
        cardState="GREEN"
        confidenceState="GREEN"
        badge={null}
      />,
    )
    expect(container.textContent).not.toMatch(/TRIPWIRE|SELL/)
  })

  it('shows SELL signal in red text', () => {
    const sellInfo = { ...baseInfo, signal: 'SELL' }
    render(
      <AssetCardHeader
        name="EURUSD"
        info={sellInfo}
        cardState="GREEN"
        confidenceState="GREEN"
        badge={null}
      />,
    )
    const signalSpan = screen.getByText('SELL')
    expect(signalSpan.className).toContain('signal-short')
  })

  it('shows FLAT signal as muted text', () => {
    const flatInfo = { ...baseInfo, signal: 'FLAT' }
    render(
      <AssetCardHeader
        name="EURUSD"
        info={flatInfo}
        cardState="GREEN"
        confidenceState="GREEN"
        badge={null}
      />,
    )
    const signalSpan = screen.getByText('FLAT')
    expect(signalSpan.className).toContain('muted')
  })
})
