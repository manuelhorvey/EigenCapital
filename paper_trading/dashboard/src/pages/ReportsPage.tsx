import { useState, useMemo } from 'react'
import Panel from '../components/ui/Panel'
import SectionHeader from '../components/ui/SectionHeader'
import { EntranceAnimator } from '../components/ui'
import { useDataExport } from '../hooks/useDataExport'
import { FileText, Download, Activity, Search } from 'lucide-react'
import { SECTION_SPACING } from '../design/grid'

interface AuditEntry {
  id: string
  timestamp: string
  action: string
  user: string
  detail: string
  severity: 'info' | 'warning' | 'error'
}

const MOCK_AUDIT_LOG: AuditEntry[] = [
  { id: '1', timestamp: new Date().toISOString(), action: 'ENGINE_START', user: 'system', detail: 'Paper trading engine initialized', severity: 'info' },
  { id: '2', timestamp: new Date(Date.now() - 3600000).toISOString(), action: 'WEEKLY_REVIEW_ACK', user: 'operator', detail: 'Weekly review acknowledged for week 28', severity: 'info' },
  { id: '3', timestamp: new Date(Date.now() - 7200000).toISOString(), action: 'HALT_CONDITION', user: 'system', detail: 'Drawdown threshold breached on EURUSD', severity: 'warning' },
  { id: '4', timestamp: new Date(Date.now() - 86400000).toISOString(), action: 'RETRAIN', user: 'system', detail: 'Model retrain completed for all 22 assets', severity: 'info' },
  { id: '5', timestamp: new Date(Date.now() - 172800000).toISOString(), action: 'CONTRACT_VERSION', user: 'system', detail: 'Contract version updated to v3.2.1', severity: 'info' },
]

type SeverityFilter = 'all' | 'info' | 'warning' | 'error'

export default function ReportsPage() {
  const [searchQuery, setSearchQuery] = useState('')
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all')
  const { exportJson, exportCsv } = useDataExport()

  const filtered = useMemo(() => {
    let entries = MOCK_AUDIT_LOG
    if (severityFilter !== 'all') {
      entries = entries.filter(e => e.severity === severityFilter)
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase()
      entries = entries.filter(e =>
        e.action.toLowerCase().includes(q) ||
        e.detail.toLowerCase().includes(q) ||
        e.user.toLowerCase().includes(q)
      )
    }
    return entries
  }, [searchQuery, severityFilter])

  return (
    <div className={SECTION_SPACING}>
      <EntranceAnimator variant="fade-up">
        <Panel padding="md">
          <SectionHeader title="Reports" accent="neutral" />
          <div className="mt-4 space-y-2">
            <button
              onClick={() => exportJson('/state-bundle.json', { filename: `eigencapital-snapshot-${Date.now()}` })}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg bg-surface/50 border border-default hover:border-strong transition-colors text-left"
            >
              <FileText className="w-4 h-4 text-accent-emerald" strokeWidth={1.5} />
              <div className="flex-1 min-w-0">
                <span className="text-xs text-primary font-medium">Portfolio State Export</span>
                <p className="text-[10px] text-tertiary mt-0.5">Download full portfolio state as JSON</p>
              </div>
              <Download className="w-3.5 h-3.5 text-tertiary shrink-0" strokeWidth={1.5} />
            </button>
            <button
              onClick={() => exportCsv('/trades.json', { filename: `trade-history-${Date.now()}` })}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg bg-surface/50 border border-default hover:border-strong transition-colors text-left"
            >
              <Activity className="w-4 h-4 text-accent-blue" strokeWidth={1.5} />
              <div className="flex-1 min-w-0">
                <span className="text-xs text-primary font-medium">Trade History Export</span>
                <p className="text-[10px] text-tertiary mt-0.5">Export all trades as CSV</p>
              </div>
              <Download className="w-3.5 h-3.5 text-tertiary shrink-0" strokeWidth={1.5} />
            </button>
            <button
              onClick={() => exportJson('/optimization.json', { filename: `optimization-data-${Date.now()}` })}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg bg-surface/50 border border-default hover:border-strong transition-colors text-left"
            >
              <Download className="w-4 h-4 text-accent-amber" strokeWidth={1.5} />
              <div className="flex-1 min-w-0">
                <span className="text-xs text-primary font-medium">Optimizer Data</span>
                <p className="text-[10px] text-tertiary mt-0.5">Export optimizer recommendations and metrics</p>
              </div>
              <Download className="w-3.5 h-3.5 text-tertiary shrink-0" strokeWidth={1.5} />
            </button>
          </div>
        </Panel>
      </EntranceAnimator>

      {/* Audit Log Viewer */}
      <EntranceAnimator variant="fade-up">
        <Panel padding="md">
          <SectionHeader title="Audit Log" accent="neutral" />
          <div className="flex items-center gap-2 mt-3 mb-3">
            <div className="flex items-center gap-1 flex-1 px-2 py-1 rounded-md bg-surface border border-default">
              <Search className="w-3 h-3 text-tertiary shrink-0" strokeWidth={1.5} />
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="Filter audit log…"
                className="flex-1 bg-transparent text-xs text-primary placeholder:text-muted outline-none"
              />
            </div>
            <div className="flex items-center gap-1">
              {(['all', 'info', 'warning', 'error'] as const).map(s => (
                <button
                  key={s}
                  onClick={() => setSeverityFilter(s)}
                  className={`px-2 py-1 rounded text-[10px] font-medium transition-colors ${
                    severityFilter === s
                      ? 'bg-panel text-primary border border-default'
                      : 'text-tertiary hover:text-secondary border border-transparent'
                  }`}
                >
                  {s.charAt(0).toUpperCase() + s.slice(1)}
                </button>
              ))}
            </div>
          </div>
          <div className="divide-y divide-default/40">
            {filtered.length === 0 ? (
              <div className="py-6 text-center text-xs text-tertiary">No matching entries</div>
            ) : (
              filtered.map(entry => (
                <div key={entry.id} className="flex items-start gap-3 py-2 px-1">
                  <span className={`mt-0.5 w-1.5 h-1.5 rounded-full shrink-0 ${
                    entry.severity === 'error' ? 'bg-gov-red' :
                    entry.severity === 'warning' ? 'bg-gov-yellow' : 'bg-gov-green'
                  }`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono font-semibold text-primary">{entry.action}</span>
                      <span className="text-[10px] text-tertiary font-mono">
                        {new Date(entry.timestamp).toLocaleString()}
                      </span>
                    </div>
                    <p className="text-[11px] text-secondary mt-0.5">{entry.detail}</p>
                  </div>
                  <span className="text-[10px] text-tertiary font-mono shrink-0">{entry.user}</span>
                </div>
              ))
            )}
          </div>
        </Panel>
      </EntranceAnimator>
    </div>
  )
}
