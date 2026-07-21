import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ChartDataTable from '../ChartDataTable'

const sampleColumns = [
  { key: 'period', label: 'Period' },
  { key: 'pnl', label: 'P&L', format: (v: unknown) => `$${Number(v).toFixed(2)}` },
  { key: 'trades', label: 'Trades', format: (v: unknown) => String(v) },
]

const sampleData: Record<string, unknown>[] = [
  { period: '2026-01', pnl: 1250.5, trades: 12 },
  { period: '2026-02', pnl: -340.2, trades: 8 },
  { period: '2026-03', pnl: 890.0, trades: 15 },
]

describe('ChartDataTable', () => {
  it('returns null when data is empty', () => {
    const { container } = render(
      <ChartDataTable title="Empty" columns={sampleColumns} data={[]} />,
    )
    expect(container.innerHTML).toBe('')
  })

  it('renders a table inside an sr-only container', () => {
    render(
      <ChartDataTable title="Test Table" columns={sampleColumns} data={sampleData} />,
    )
    const container = document.querySelector('.sr-only')
    expect(container).toBeInTheDocument()
    const table = container!.querySelector('table')
    expect(table).toBeInTheDocument()
  })

  it('sets aria-label on the table from the title prop', () => {
    render(
      <ChartDataTable title="Cumulative P&L" columns={sampleColumns} data={sampleData} />,
    )
    const table = screen.getByRole('table')
    expect(table).toHaveAttribute('aria-label', 'Cumulative P&L')
  })

  it('sets summary attribute on the table when provided', () => {
    render(
      <ChartDataTable
        title="Test"
        columns={sampleColumns}
        data={sampleData}
        summary="P&L breakdown across 3 months"
      />,
    )
    const table = screen.getByRole('table')
    expect(table).toHaveAttribute('summary', 'P&L breakdown across 3 months')
  })

  it('renders all column headers with correct text and scope', () => {
    render(
      <ChartDataTable title="Test" columns={sampleColumns} data={sampleData} />,
    )
    const headers = screen.getAllByRole('columnheader')
    expect(headers).toHaveLength(3)
    expect(headers[0]).toHaveTextContent('Period')
    expect(headers[1]).toHaveTextContent('P&L')
    expect(headers[2]).toHaveTextContent('Trades')
    headers.forEach(th => {
      expect(th).toHaveAttribute('scope', 'col')
    })
  })

  it('renders data rows with correct number of cells', () => {
    render(
      <ChartDataTable title="Test" columns={sampleColumns} data={sampleData} />,
    )
    const rows = screen.getAllByRole('row')
    // 1 header row + 3 data rows
    expect(rows).toHaveLength(4)
    const dataRows = rows.slice(1)
    expect(dataRows).toHaveLength(3)
  })

  it('renders raw cell values when no format function is provided', () => {
    const columnsNoFormat = [
      { key: 'period', label: 'Period' },
      { key: 'pnl', label: 'P&L' },
    ]
    render(
      <ChartDataTable title="Test" columns={columnsNoFormat} data={sampleData} />,
    )
    expect(screen.getByText('2026-01')).toBeInTheDocument()
    expect(screen.getByText('1250.5')).toBeInTheDocument()
    expect(screen.getByText('2026-03')).toBeInTheDocument()
  })

  it('applies format functions to cell values', () => {
    render(
      <ChartDataTable title="Test" columns={sampleColumns} data={sampleData} />,
    )
    expect(screen.getByText('$1250.50')).toBeInTheDocument()
    expect(screen.getByText('$-340.20')).toBeInTheDocument()
    expect(screen.getByText('$890.00')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('8')).toBeInTheDocument()
    expect(screen.getByText('15')).toBeInTheDocument()
  })

  it('renders caption when provided', () => {
    render(
      <ChartDataTable
        title="Test"
        columns={sampleColumns}
        data={sampleData}
        caption="P&L data for Q1 2026"
      />,
    )
    expect(screen.getByText('P&L data for Q1 2026')).toBeInTheDocument()
  })

  it('does not render caption when omitted', () => {
    const { container } = render(
      <ChartDataTable title="Test" columns={sampleColumns} data={sampleData} />,
    )
    expect(container.querySelector('caption')).not.toBeInTheDocument()
  })

  it('handles null and missing values gracefully', () => {
    const sparseData: Record<string, unknown>[] = [
      { period: '2026-01', pnl: null, trades: undefined },
    ]
    render(
      <ChartDataTable title="Test" columns={sampleColumns} data={sparseData} />,
    )
    // Null: format function receives null, Number(null) = 0, so "$0.00"
    expect(screen.getByText('$0.00')).toBeInTheDocument()
    // Undefined: format function receives undefined, Number(undefined) = NaN → "$NaN.00"
    // But String(undefined) = "undefined" — test the fallback
    expect(screen.getByText('undefined')).toBeInTheDocument()
  })

  it('renders empty columns array without crashing', () => {
    const { container } = render(
      <ChartDataTable title="Test" columns={[]} data={sampleData} />,
    )
    const table = container.querySelector('table')
    expect(table).toBeInTheDocument()
    const headerRow = table!.querySelector('thead tr')
    expect(headerRow!.children).toHaveLength(0) // no <th> elements
    const dataRows = table!.querySelectorAll('tbody tr')
    expect(dataRows).toHaveLength(3)
    // Each row has 0 <td> elements since there are no columns
    dataRows.forEach(row => {
      expect(row.querySelectorAll('td')).toHaveLength(0)
    })
  })

  it('renders with a single row of data', () => {
    const singleRow: Record<string, unknown>[] = [
      { period: '2026-01', pnl: 500, trades: 1 },
    ]
    render(
      <ChartDataTable title="Single Row" columns={sampleColumns} data={singleRow} />,
    )
    expect(screen.getAllByRole('row')).toHaveLength(2) // header + 1 data row
    expect(screen.getByText('$500.00')).toBeInTheDocument()
  })

  it('renders aria-hidden false on the sr-only wrapper for screen reader compatibility', () => {
    render(
      <ChartDataTable title="Test" columns={sampleColumns} data={sampleData} />,
    )
    const wrapper = document.querySelector('.sr-only')
    expect(wrapper).toHaveAttribute('aria-hidden', 'false')
  })
})
