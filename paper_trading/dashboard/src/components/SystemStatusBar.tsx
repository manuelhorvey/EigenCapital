import { memo } from 'react'
import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { selectMeta } from '../selectors/system'
import { formatTimeAgo } from '../utils/format'
import { Activity } from 'lucide-react'
import type { z } from 'zod'
import type { SystemBundleSchema } from '../lib/schemas'

type Meta = z.infer<typeof SystemBundleSchema>['meta']

const STATUS_STYLES: Record<string, { dot: string; label: string; bg: string }> = {
  ok: { dot: 'bg-gov-green', label: 'LIVE', bg: 'bg-gov-green/10 border-gov-green/20 text-gov-green' },
  live: { dot: 'bg-gov-green', label: 'LIVE', bg: 'bg-gov-green/10 border-gov-green/20 text-gov-green' },
  degraded: { dot: 'bg-gov-yellow', label: 'DEGRADED', bg: 'bg-gov-yellow/10 border-gov-yellow/20 text-gov-yellow' },
  partial_failure: { dot: 'bg-gov-yellow', label: 'DEGRADED', bg: 'bg-gov-yellow/10 border-gov-yellow/20 text-gov-yellow' },
  offline: { dot: 'bg-gov-red', label: 'OFFLINE', bg: 'bg-gov-red/10 border-gov-red/20 text-gov-red' },
}

function SystemStatusBarInner() {
  const { data: meta } = useSystemSnapshot(selectMeta) as { data: Meta | undefined }
  const seqId = meta?.snapshot_sequence_id
  const snapshotTime = meta?.snapshot_time
  const s = STATUS_STYLES[meta?.status ?? 'offline'] ?? STATUS_STYLES.offline

  return (
    <div className="flex items-center justify-between px-3 py-1.5 bg-surface border-b border-default text-2xs font-mono tabular-nums">
      <div className="flex items-center gap-3">
        <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[10px] font-semibold tracking-wider ${s.bg}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
          {s.label}
        </span>
        {seqId != null && (
          <span className="text-tertiary">
            SEQ <span className="text-secondary">#{seqId}</span>
          </span>
        )}
        <span className="text-tertiary flex items-center gap-1">
          <Activity className="w-3 h-3" strokeWidth={1.5} />
          {snapshotTime ? formatTimeAgo(snapshotTime) : '—'}
        </span>
      </div>
      <div className="flex items-center gap-2 text-tertiary">
        {meta?.version && <span>v{meta.version}</span>}
        {meta?.request_id && (
          <span className="hidden sm:inline" title={meta.request_id}>
            req:{meta.request_id.slice(0, 8)}
          </span>
        )}
      </div>
    </div>
  )
}

const SystemStatusBar = memo(SystemStatusBarInner)
SystemStatusBar.displayName = 'SystemStatusBar'
export default SystemStatusBar
