import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import OverviewTab from '../OverviewTab'
import { buildAssetState } from './mocks'

describe('OverviewTab', () => {
  it('renders final signal and raw signal', () => {
    render(<OverviewTab asset={buildAssetState()} />)
    // Both final_signal and last_signal.signal are 'BUY'
    const buyElements = screen.getAllByText('BUY')
    expect(buyElements.length).toBe(2)
    expect(screen.getByText('68.5')).toBeInTheDocument() // confidence
    expect(screen.getByText('LONG')).toBeInTheDocument() // validity state
    expect(screen.getByText('ACTIVE')).toBeInTheDocument() // execution state
  })

  it('shows finalSignal derived from position side when null and position exists', () => {
    const asset = buildAssetState({
      final_signal: null,
      metrics: {
        ...buildAssetState().metrics,
        position: { side: 'long', entry: 1.10, sl: 1.09, tp: 1.12, current_vol: 1, unrealized_pnl: 50, sl_mult: 2, tp_mult: 1.5 },
      },
    })
    render(<OverviewTab asset={asset} />)
    expect(screen.getByText('LONG')).toBeInTheDocument() // position side
  })

  it('shows FLAT when final_signal is null and no position', () => {
    const asset = buildAssetState({ final_signal: null })
    render(<OverviewTab asset={asset} />)
    const flats = screen.getAllByText('FLAT')
    expect(flats.length).toBeGreaterThanOrEqual(1)
  })

  it('shows signal flip warning when signal_flip is true', () => {
    const asset = buildAssetState({ signal_flip: true })
    render(<OverviewTab asset={asset} />)
    expect(screen.getByText(/Signal flip detected/)).toBeInTheDocument()
  })

  it('renders performance section with all metric rows', () => {
    render(<OverviewTab asset={buildAssetState()} />)
    expect(screen.getByText(/3\.25%/)).toBeInTheDocument() // total return
    expect(screen.getByText(/-1\.50%/)).toBeInTheDocument() // drawdown
    expect(screen.getByText(/1\.85/)).toBeInTheDocument()   // profit factor
    expect(screen.getByText(/62%/)).toBeInTheDocument()      // win rate
    expect(screen.getByText(/1\.25/)).toBeInTheDocument()    // sharpe
    expect(screen.getByText('45')).toBeInTheDocument()       // trades
    expect(screen.getByText('180')).toBeInTheDocument()      // signals
  })

  it('renders signal distribution', () => {
    render(<OverviewTab asset={buildAssetState()} />)
    expect(screen.getByText(/B:80/)).toBeInTheDocument()
    expect(screen.getByText(/S:60/)).toBeInTheDocument()
    expect(screen.getByText(/F:40/)).toBeInTheDocument()
  })

  it('renders exit reason breakdown', () => {
    render(<OverviewTab asset={buildAssetState()} />)
    // tp_rate=0.2 → 20%, sl_rate=0.5 → 50%, etc.
    expect(screen.getByText(/20\/50\/5\/15\/10%/)).toBeInTheDocument()
  })

  it('renders position section when position exists', () => {
    const asset = buildAssetState({
      metrics: {
        ...buildAssetState().metrics,
        position: { side: 'long', entry: 1.1000, sl: 1.0950, tp: 1.1100, current_vol: 2, unrealized_pnl: 25.50, sl_mult: 2, tp_mult: 1.5 },
      },
    })
    render(<OverviewTab asset={asset} />)
    expect(screen.getByText('LONG')).toBeInTheDocument()
    expect(screen.getByText(/1\.1000/)).toBeInTheDocument()  // entry
    expect(screen.getByText(/1\.0950/)).toBeInTheDocument()  // sl
    expect(screen.getByText(/1\.1100/)).toBeInTheDocument()  // tp
    expect(screen.getByText(/25\.50%/)).toBeInTheDocument()  // unrealized PnL
    expect(screen.getByText('2.00')).toBeInTheDocument()     // volume
  })

  it('does not render position section when no position', () => {
    const asset = buildAssetState()
    const { container } = render(<OverviewTab asset={asset} />)
    expect(container.textContent).not.toMatch(/Entry/)
  })

  it('renders current price', () => {
    render(<OverviewTab asset={buildAssetState()} />)
    expect(screen.getByText(/1\.1050/)).toBeInTheDocument()
  })

  it('handles null current_price gracefully', () => {
    const asset = buildAssetState({
      metrics: { ...buildAssetState().metrics, current_price: null },
    })
    render(<OverviewTab asset={asset} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })
})
