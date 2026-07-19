import { useCallback } from 'react'
import { fetchApi } from '../lib/api'

type ExportFormat = 'csv' | 'json'

interface ExportOptions {
  filename: string
  format?: ExportFormat
}

function jsonToCsv(json: unknown[], columns?: string[]): string {
  if (json.length === 0) return ''
  const keys = columns ?? Object.keys(json[0] as Record<string, unknown>)
  const header = keys.join(',')
  const rows = json.map((row) => {
    const r = row as Record<string, unknown>
    return keys.map((k) => {
      const v = r[k]
      if (v == null) return ''
      const s = String(v)
      return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s.replace(/"/g, '""')}"` : s
    }).join(',')
  })
  return [header, ...rows].join('\n')
}

function download(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function useDataExport() {
  const exportJson = useCallback(async (endpoint: string, options: ExportOptions) => {
    const data = await fetchApi<unknown>(endpoint)
    const json = JSON.stringify(data, null, 2)
    download(json, `${options.filename}.json`, 'application/json')
  }, [])

  const exportCsv = useCallback(async (endpoint: string, options: ExportOptions & { columns?: string[] }) => {
    const data = await fetchApi<unknown[]>(endpoint)
    if (!Array.isArray(data)) {
      console.warn('[export] Data is not an array, cannot convert to CSV')
      return
    }
    const csv = jsonToCsv(data, options.columns)
    download(csv, `${options.filename}.csv`, 'text/csv')
  }, [])

  const exportTable = useCallback((rows: Record<string, unknown>[], filename: string, columns?: string[]) => {
    const csv = jsonToCsv(rows, columns)
    download(csv, `${filename}.csv`, 'text/csv')
  }, [])

  return { exportJson, exportCsv, exportTable }
}
