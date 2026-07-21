import { useState, useMemo, useCallback, memo } from 'react'
import { Search, Filter, Clock, AlertTriangle, Info, Download, Shield, Activity, RefreshCw } from 'lucide-react'
import { useMonitorAlerts, type Alert } from '../hooks/useMonitorAlerts'
import { useNotificationCenter, type Notification } from '../hooks/useNotificationCenter'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import Panel from './ui/Panel'
import { SECTION_SPACING } from '../design/grid'
import { formatTimeAgo } from '../utils/format'

// ── Types ──────────────────────────────────────────────────────────

export type AuditEntrySeverity = 'critical' | 'warning' | 'info' | 'error'
export type AuditEntryType = 'halt' | 'health' | 'governance' | 'performance' | 'notification' | 'system' | 'trade'

export interface AuditEntry {
  id: string
  timestamp: string
  severity: AuditEntrySeverity
  type: AuditEntryType
  title: string
  message: string
  asset?: string
  detail?: string
  source: 'alert' | 'notification' | 'system'
}

// ── Helpers ────────────────────────────────────────────────────────

function notifToAuditEntry(n: Notification): AuditEntry {
  return {
    id: `notif-${n.id}`,
    timestamp: new Date(n.timestamp).toISOString(),
    severity: n.type === 'error' ? 'error' : n.type === 'warning' ? 'warning' : 'info',
    type: 'notification',
    title: n.title,
    message: n.message ?? '',
    source: 'notification',
  }
}

function alertToAuditEntry(a: Alert): AuditEntry {
  return {
    id: `alert-${a.id}`,
    timestamp: a.timestamp,
    severity: a.severity,
    type: a.type,
    title: a.message,
    message: a.detail ?? '',
    asset: a.asset,
    source: 'alert',
  }
}

function severityColor(sev: AuditEntrySeverity): string {
  switch (sev) {
    case 'critical': return 'var(--color-signal-short)'
    case 'error': return 'var(--color-signal-short)'
    case 'warning': return 'var(--color-signal-warn)'
    case 'info': return 'var(--color-signal-long)'
  }
}

function severityBg(sev: AuditEntrySeverity): string {
  switch (sev) {
    case 'critical': return 'bg-signal-short-muted'
    case 'error': return 'bg-signal-short-muted'
    case 'warning': return 'bg-signal-warn-muted'
    case 'info': return 'bg-signal-long-muted'
  }
}

// ── Components ─────────────────────────────────────────────────────

// Pre-computed icon lookup for TypeIcon (avoids switch re-evaluation on every render)
const TYPE_ICONS: Record<AuditEntryType, React.ReactNode> = {
  halt: <Shield className="w-3 h-3" strokeWidth={2} />,
  health: <Activity className="w-3 h-3" strokeWidth={2} />,
  governance: <AlertTriangle className="w-3 h-3" strokeWidth={2} />,
  performance: <RefreshCw className="w-3 h-3" strokeWidth={2} />,
  notification: <Info className="w-3 h-3" strokeWidth={2} />,
  system: <Activity className="w-3 h-3" strokeWidth={2} />,
  trade: <Activity className="w-3 h-3" strokeWidth={2} />,
}

const SeverityDot = memo(function SeverityDot({ severity }: { severity: AuditEntrySeverity }) {
  return (
    <span
      className="w-1.5 h-1.5 rounded-full shrink-0 mt-0.5"
      style={{ backgroundColor: severityColor(severity) }}
    />
  )
})

function TypeIcon({ type }: { type: AuditEntryType }) {
  return TYPE_ICONS[type] ?? null
}

interface AuditLogViewerProps {
  /** Optional initial filter defaults */
  defaultFilters?: {
    severity?: AuditEntrySeverity[]
    type?: AuditEntryType[]
  }
  /** Max entries to show before pagination. Default 200. */
  maxEntries?: number
  /** Height of the scrollable list. Default 'max-h-[600px]'. */
  listHeight?: string
}

export default function AuditLogViewer({
  maxEntries = 200,
  listHeight = 'max-h-[600px]',
}: AuditLogViewerProps) {
  const [search, setSearch] = useState('')
  const [severityFilter, setSeverityFilter] = useState<AuditEntrySeverity | 'all'>('all')
  const [typeFilter, setTypeFilter] = useState<AuditEntryType | 'all'>('all')
  const [showFilters, setShowFilters] = useState(false)
  const [showCount, setShowCount] = useState(50)
  // Uses inline CSV generation for direct filter-aware export (no hook needed)

  // Data sources
  const alerts = useMonitorAlerts()
  const { notifications } = useNotificationCenter()
  const { data: snapshot } = useSystemSnapshot(systemSelectors.snapshot)

  // Merge entries from all sources
  const entries: AuditEntry[] = useMemo(() => {
    const result: AuditEntry[] = []

    // System-level events from snapshot (not portfolio sub-object)
    if (snapshot) {
      if (snapshot.emergency_halt) {
        result.push({
          id: 'sys-halt',
          timestamp: snapshot.timestamp,
          severity: 'critical',
          type: 'halt',
          title: 'Emergency Halt Active',
          message: snapshot.halt_reason || snapshot.halt_detail || 'System emergency halt triggered',
          source: 'system',
        })
      }

      // Portfolio-level events
      const p = snapshot.portfolio
      if (p?.admission?.n_rejected && p.admission.n_rejected > 0) {
        result.push({
          id: 'sys-rejection',
          timestamp: snapshot.timestamp,
          severity: 'warning',
          type: 'governance',
          title: `${p.admission.n_rejected} signals rejected`,
          message: `Admission gate rejected ${p.admission.n_rejected} of ${p.admission.n_intents} signals`,
          source: 'system',
          detail: Object.entries(p.admission.rejection_reasons || {}).map(([a, r]) => `${a}: ${r}`).join(', '),
        })
      }
    }

    // Engine status events
    if (snapshot?.engine_status) {
      const es = snapshot.engine_status
      if (!es.initialized) {
        result.push({
          id: 'sys-not-initialized',
          timestamp: snapshot.timestamp,
          severity: 'warning',
          type: 'system',
          title: 'Engine not initialized',
          message: `Engine status: initialized=${es.initialized}`,
          source: 'system',
        })
      }
      if (es.initialized && es.start_time) {
        result.push({
          id: 'sys-engine-started',
          timestamp: es.start_time,
          severity: 'info',
          type: 'system',
          title: 'Engine started',
          message: `Engine started at ${es.start_time}`,
          source: 'system',
        })
      }
    }

    // Alerts
    for (const a of alerts) {
      result.push(alertToAuditEntry(a))
    }

    // Notifications (last 100)
    for (const n of notifications.slice(-100)) {
      result.push(notifToAuditEntry(n))
    }

    // Sort by timestamp (most recent first)
    result.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())

    return result
  }, [alerts, notifications, snapshot])

  // Apply filters
  const filtered = useMemo(() => {
    return entries.filter(e => {
      if (severityFilter !== 'all' && e.severity !== severityFilter) return false
      if (typeFilter !== 'all' && e.type !== typeFilter) return false
      if (search) {
        const q = search.toLowerCase()
        return (
          e.title.toLowerCase().includes(q) ||
          e.message.toLowerCase().includes(q) ||
          (e.asset?.toLowerCase().includes(q)) ||
          e.id.toLowerCase().includes(q)
        )
      }
      return true
    })
  }, [entries, severityFilter, typeFilter, search])

  const display = useMemo(() => filtered.slice(0, showCount), [filtered, showCount])
  const hasMore = filtered.length > showCount

  const uniqueTypes = useMemo(() => [...new Set(entries.map(e => e.type))], [entries])
  const severityCounts = useMemo(() => {
    const counts = { critical: 0, warning: 0, info: 0, error: 0 }
    for (const e of entries) counts[e.severity]++
    return counts
  }, [entries])

  const handleExport = useCallback(() => {
    const rows = filtered.map(e => ({
      timestamp: e.timestamp,
      severity: e.severity,
      type: e.type,
      title: e.title,
      message: e.message,
      asset: e.asset ?? '',
    }))
    const csv = [
      'timestamp,severity,type,title,message,asset',
      ...rows.map(r =>
        `"${r.timestamp}","${r.severity}","${r.type}","${r.title.replace(/"/g, '""')}","${r.message.replace(/"/g, '""')}","${r.asset}"`,
      ),
    ].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `audit-log-${Date.now()}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }, [filtered])

  return (
    <div className={SECTION_SPACING}>
      {/* Search & Filter Bar */}
      <div className="flex items-center gap-2 mb-2">
        <div className="flex items-center gap-1 flex-1 px-2.5 py-1.5 rounded-md bg-surface border border-default focus-within:border-strong transition-colors">
          <Search className="w-3 h-3 text-tertiary shrink-0" strokeWidth={1.5} />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search audit log…"
            className="flex-1 bg-transparent text-xs text-primary placeholder:text-muted outline-none"
          />
          {search && (
            <button onClick={() => setSearch('')} className="text-tertiary hover:text-secondary text-[10px] px-1">✕</button>
          )}
        </div>
        <button
          onClick={() => setShowFilters(!showFilters)}
          className={`flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors ${
            showFilters || severityFilter !== 'all' || typeFilter !== 'all'
              ? 'bg-panel text-primary border border-default'
              : 'text-tertiary hover:text-secondary border border-transparent'
          }`}
        >
          <Filter className="w-3 h-3" strokeWidth={1.5} />
          Filters
        </button>
        <button
          onClick={handleExport}
          className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs font-medium text-tertiary hover:text-secondary hover:bg-surface transition-colors"
          title="Export as CSV"
        >
          <Download className="w-3 h-3" strokeWidth={1.5} />
        </button>
      </div>

      {/* Expanded Filters */}
      {showFilters && (
        <div className="flex flex-wrap items-center gap-2 mb-3 px-3 py-2 rounded-lg bg-surface/50 border border-default">
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-[10px] text-tertiary font-medium mr-1">Severity:</span>
            {(['all', 'critical', 'warning', 'info', 'error'] as const).map(s => (
              <button
                key={s}
                onClick={() => setSeverityFilter(s)}
                className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                  severityFilter === s
                    ? s === 'all' ? 'bg-panel text-primary border border-default'
                      : `${severityBg(s)} border border-default`
                    : 'text-tertiary hover:text-secondary border border-transparent'
                }`}
              >
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </button>
            ))}
          </div>
          <div className="w-px h-4 bg-default/50" />
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-[10px] text-tertiary font-medium mr-1">Type:</span>
            <select
              value={typeFilter}
              onChange={e => setTypeFilter(e.target.value as AuditEntryType | 'all')}
              className="text-[10px] bg-surface border border-default rounded px-2 py-0.5 text-primary outline-none"
            >
              <option value="all">All types</option>
              {uniqueTypes.map(t => (
                <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
              ))}
            </select>
          </div>
        </div>
      )}

      {/* Summary Bar */}
      <div className="flex items-center gap-3 mb-3 text-2xs text-tertiary font-mono">
        <span>{entries.length} total entries</span>
        {severityCounts.critical > 0 && <span className="text-signal-short">{severityCounts.critical} critical</span>}
        {severityCounts.warning > 0 && <span className="text-signal-warn">{severityCounts.warning} warnings</span>}
        {filtered.length < entries.length && <span>· {filtered.length} filtered</span>}
      </div>

      {/* Audit List */}
      <Panel padding="none">
        <div className={`divide-y divide-default/30 overflow-y-auto ${listHeight}`}>
          {display.length === 0 ? (
            <div className="py-10 text-center">
              <div className="inline-flex items-center justify-center w-10 h-10 rounded-full bg-surface border border-default mb-2">
                <Clock className="w-5 h-5 text-tertiary" strokeWidth={1.5} />
              </div>
              <p className="text-sm text-tertiary">No audit entries</p>
              <p className="text-xs text-muted mt-1">
                {search || severityFilter !== 'all' || typeFilter !== 'all'
                  ? 'Try adjusting filters'
                  : 'Audit log will populate as events occur'}
              </p>
            </div>
          ) : (
            <>
              {display.map(entry => (
                <div
                  key={entry.id}
                  className="flex items-start gap-3 px-4 py-2.5 hover:bg-surface/30 transition-colors group"
                >
                  <SeverityDot severity={entry.severity} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="flex items-center gap-1 text-xs font-semibold text-primary">
                        <span className="flex items-center gap-1 text-[10px] text-tertiary font-normal opacity-60">
                          <TypeIcon type={entry.type} />
                        </span>
                        {entry.title}
                      </span>
                      {entry.asset && (
                        <span className="text-[10px] font-mono font-medium px-1.5 py-px rounded bg-surface text-tertiary border border-default/50">
                          {entry.asset}
                        </span>
                      )}
                    </div>
                    {entry.message && (
                      <p className="text-[11px] text-secondary mt-0.5 line-clamp-2">{entry.message}</p>
                    )}
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-[10px] text-muted font-mono">{formatTimeAgo(entry.timestamp)}</span>
                      <span className="text-[10px] text-muted font-medium uppercase">{entry.severity}</span>
                      <span className="text-[10px] text-muted font-medium">{entry.type}</span>
                    </div>
                  </div>
                  <span className="text-[10px] text-muted font-mono shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                    {entry.source}
                  </span>
                </div>
              ))}
            </>
          )}
        </div>

        {/* Load More / Summary */}
        {hasMore && (
          <div className="flex items-center justify-between px-4 py-2 border-t border-default bg-surface/30">
            <span className="text-2xs text-tertiary font-mono">
              Showing {display.length} of {filtered.length} entries
            </span>
            <button
              onClick={() => setShowCount(prev => Math.min(prev + 50, maxEntries))}
              className="text-[10px] font-medium text-accent-emerald hover:text-emerald-400 transition-colors"
            >
              Load more
            </button>
          </div>
        )}
        {!hasMore && filtered.length > 0 && (
          <div className="px-4 py-1.5 border-t border-default text-2xs text-muted text-center font-mono">
            All {filtered.length} entries shown
          </div>
        )}
      </Panel>
    </div>
  )
}
