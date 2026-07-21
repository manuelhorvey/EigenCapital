import Panel from '../components/ui/Panel'
import SectionHeader from '../components/ui/SectionHeader'
import { EntranceAnimator } from '../components/ui'
import AuditLogViewer from '../components/AuditLogViewer'
import { useDataExport } from '../hooks/useDataExport'
import { FileText, Download, Activity } from 'lucide-react'
import { SECTION_SPACING } from '../design/grid'

export default function ReportsPage() {
  const { exportJson, exportCsv } = useDataExport()

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

      {/* Audit Log Viewer — replaces mock audit log with live event aggregation */}
      <EntranceAnimator variant="fade-up">
        <Panel padding="md">
          <SectionHeader title="Audit Log" accent="neutral" />
          <AuditLogViewer maxEntries={500} listHeight="max-h-[600px]" />
        </Panel>
      </EntranceAnimator>
    </div>
  )
}
