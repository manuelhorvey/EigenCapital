import { useState, useMemo, useCallback } from 'react'
import type { ColumnDef } from '../components/ui/DataTable'

type SortDir = 'asc' | 'desc' | null

interface UseTableSortOptions {
  sortable?: boolean
  defaultSortKey?: string
  defaultSortDir?: 'asc' | 'desc'
  storageKey?: string
  onSortChange?: (col: string | null, dir: SortDir) => void
}

interface UseTableSortResult<T> {
  sortCol: string | null
  sortDir: SortDir
  sortedData: T[]
  toggleSort: (key: string) => void
  sortAria: (key: string) => 'none' | 'ascending' | 'descending'
}

function loadSort(key: string): { col: string; dir: SortDir } | null {
  try {
    const v = sessionStorage.getItem(`ec_sort_${key}`)
    return v ? JSON.parse(v) : null
  } catch { return null }
}

function saveSort(key: string, col: string, dir: SortDir) {
  try { sessionStorage.setItem(`ec_sort_${key}`, JSON.stringify({ col, dir })) } catch {}
}

export function useTableSort<T>(
  data: T[],
  columns: ColumnDef<T>[],
  options: UseTableSortOptions = {},
): UseTableSortResult<T> {
  const { sortable = false, defaultSortKey, defaultSortDir = 'desc', storageKey, onSortChange } = options

  const initial = storageKey ? loadSort(storageKey) : null
  const [sortCol, setSortCol] = useState<string | null>(initial?.col ?? defaultSortKey ?? null)
  const [sortDir, setSortDir] = useState<SortDir>(initial?.dir ?? defaultSortDir)

  const sortedData = useMemo(() => {
    if (!sortCol || !sortDir || !sortable) return data
    const col = columns.find(c => c.key === sortCol)
    if (!col?.sortable) return data
    const fn = col.sortKey ?? ((r: T) => r[sortCol as keyof T] as unknown as string | number)
    return [...data].sort((a, b) => {
      const va = fn(a)
      const vb = fn(b)
      if (typeof va === 'number' && typeof vb === 'number') {
        return sortDir === 'asc' ? va - vb : vb - va
      }
      return sortDir === 'asc'
        ? String(va).localeCompare(String(vb))
        : String(vb).localeCompare(String(va))
    })
  }, [data, sortCol, sortDir, columns, sortable])

  const toggleSort = useCallback((key: string) => {
    if (!sortable) return
    const next: SortDir = sortCol === key
      ? (sortDir === 'asc' ? 'desc' : sortDir === 'desc' ? null : 'asc')
      : 'desc'
    const nextCol = next === null ? null : key
    setSortCol(nextCol)
    setSortDir(next)
    if (storageKey && next && nextCol) saveSort(storageKey, nextCol, next)
    onSortChange?.(nextCol, next)
  }, [sortable, sortCol, sortDir, storageKey, onSortChange])

  const sortAria = useCallback((key: string): 'none' | 'ascending' | 'descending' => {
    if (sortCol !== key || !sortDir) return 'none'
    return sortDir === 'asc' ? 'ascending' : 'descending'
  }, [sortCol, sortDir])

  return { sortCol, sortDir, sortedData, toggleSort, sortAria }
}
