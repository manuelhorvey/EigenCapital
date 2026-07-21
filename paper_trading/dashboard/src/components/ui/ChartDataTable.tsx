interface Column {
  key: string
  label: string
  format?: (value: unknown) => string
}

interface ChartDataTableProps {
  /** Title announced to screen readers for the data table */
  title: string
  /** Column definitions */
  columns: Column[]
  /** Data rows */
  data: Record<string, unknown>[]
  /** Optional caption visible to screen readers describing the context */
  caption?: string
  /** Summary of the data for screen reader context */
  summary?: string
}

/**
 * Accessible data table for chart data.
 * Rendered visually hidden (`sr-only`) so screen reader users can
 * navigate the underlying numbers in a structured table format.
 *
 * Place this component alongside a visual chart (Recharts, D3, etc.)
 * to provide the same data in an accessible tabular format.
 *
 * Usage:
 *   <ChartDataTable
 *     title="Cumulative P&L by period"
 *     columns={[
 *       { key: 'period', label: 'Period' },
 *       { key: 'pnl', label: 'Period P&L', format: v => `$${Number(v).toFixed(2)}` },
 *       { key: 'cumulative', label: 'Cumulative P&L', format: v => `$${Number(v).toFixed(2)}` },
 *     ]}
 *     data={chartData}
 *     summary="P&L breakdown showing period and cumulative values across 12 months"
 *   />
 */
export default function ChartDataTable({
  title,
  columns,
  data,
  caption,
  summary,
}: ChartDataTableProps) {
  if (data.length === 0) return null

  return (
    <div className="sr-only" aria-hidden={false}>
      <table
        aria-label={title}
        summary={summary}
        role="table"
      >
        {caption && <caption>{caption}</caption>}
        <thead>
          <tr>
            {columns.map(col => (
              <th key={col.key} scope="col">{col.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, rowIdx) => (
            <tr key={rowIdx}>
              {columns.map(col => (
                <td key={col.key}>
                  {col.format
                    ? col.format(row[col.key])
                    : String(row[col.key] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
