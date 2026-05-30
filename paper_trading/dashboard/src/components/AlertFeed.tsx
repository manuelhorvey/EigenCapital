import { useState, useMemo, useEffect } from 'react'
import { Bell, BellOff, AlertTriangle, Shield, TrendingDown, RotateCcw, X } from 'lucide-react'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'
import { useGovernance } from '../hooks/useGovernance'
import { usePSI } from '../hooks/usePSI'
import { usePortfolioState } from '../hooks/usePortfolioState'

const STORAGE_KEY = 'qf_alert_feed'

interface AlertEvent {
  id: string
  ts: number
  type: 'halt' | 'state_change' | 'psi_severe' | 'narrative' | 'sl_hit'
  asset: string
  severity: 'high' | 'medium' | 'low'
  message: string
}

function loadAlerts(): AlertEvent[] {
  try {
    const v = sessionStorage.getItem(STORAGE_KEY)
    return v ? JSON.parse(v) : []
  } catch { return [] }
}

function saveAlerts(alerts: AlertEvent[]) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(alerts.slice(-100)))
  } catch {}
}

function severityIcon(sev: AlertEvent['severity']) {
  switch (sev) {
    case 'high': return <AlertTriangle className="w-3 h-3 text-gov-red" strokeWidth={2} />
    case 'medium': return <Shield className="w-3 h-3 text-gov-yellow" strokeWidth={2} />
    case 'low': return <RotateCcw className="w-3 h-3 text-muted" strokeWidth={2} />
  }
}

function formatAlertTime(ts: number): string {
  const seconds = Math.floor((Date.now() - ts) / 1000)
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  return `${hours}h ago`
}

let alertIdCounter = Date.now()
function nextId(): string {
  return `alert_${++alertIdCounter}`
}

export default function AlertFeed() {
  const [open, setOpen] = useState(false)
  const [alerts, setAlerts] = useState<AlertEvent[]>(loadAlerts)
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())

  const { data: govData, dataUpdatedAt: govUpdatedAt } = useGovernance()
  const { data: psiData } = usePSI()
  const { data: stateData } = usePortfolioState()

  useEffect(() => {
    if (!govData) return
    const newAlerts: AlertEvent[] = []
    for (const [asset, state] of Object.entries(govData)) {
      if (state.halted) {
        newAlerts.push({
          id: nextId(),
          ts: Date.now(),
          type: 'halt',
          asset,
          severity: 'high',
          message: `${asset} halted by governance`,
        })
      }
      if (!state.halted && state.soft_warnings?.length > 0) {
        for (const w of state.soft_warnings) {
          newAlerts.push({
            id: nextId(),
            ts: Date.now(),
            type: 'narrative',
            asset,
            severity: 'low',
            message: `${asset}: ${w}`,
          })
        }
      }
      if (state.validity_state === 'RED') {
        newAlerts.push({
          id: nextId(),
          ts: Date.now(),
          type: 'state_change',
          asset,
          severity: 'high',
          message: `${asset} validity state is RED`,
        })
      }
    }
    if (newAlerts.length > 0) {
      setAlerts(prev => {
        const existing = new Set(prev.map(a => `${a.asset}:${a.type}`))
        const unique = newAlerts.filter(a => !existing.has(`${a.asset}:${a.type}`))
        if (unique.length === 0) return prev
        const combined = [...unique, ...prev]
        saveAlerts(combined)
        return combined
      })
    }
  }, [govData, govUpdatedAt])

  useEffect(() => {
    if (!psiData) return
    const newAlerts: AlertEvent[] = []
    for (const [asset, status] of Object.entries(psiData)) {
      if (status.severe_count > 0) {
        newAlerts.push({
          id: nextId(),
          ts: Date.now(),
          type: 'psi_severe',
          asset,
          severity: 'medium',
          message: `${asset}: ${status.severe_count} severe PSI feature(s)`,
        })
      }
    }
    if (newAlerts.length > 0) {
      setAlerts(prev => {
        const existing = new Set(prev.map(a => `${a.asset}:${a.type}`))
        const unique = newAlerts.filter(a => !existing.has(`${a.asset}:${a.type}`))
        if (unique.length === 0) return prev
        const combined = [...unique, ...prev]
        saveAlerts(combined)
        return combined
      })
    }
  }, [psiData])

  const unreadCount = alerts.filter(a => !dismissed.has(a.id)).length

  const dismiss = (id: string) => {
    setDismissed(prev => new Set(prev).add(id))
  }

  const dismissAll = () => {
    setDismissed(prev => new Set([...alerts.map(a => a.id), ...prev]))
  }

  const visibleAlerts = useMemo(
    () => alerts.filter(a => !dismissed.has(a.id)).slice(0, 50),
    [alerts, dismissed],
  )

  return (
    <Panel padding="none" className="overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 text-xs font-medium text-secondary hover:bg-panel/50 transition-colors border-b border-default"
      >
        <div className="flex items-center gap-2">
          {unreadCount > 0 ? (
            <Bell className="w-3.5 h-3.5 text-gov-yellow" strokeWidth={1.5} />
          ) : (
            <BellOff className="w-3.5 h-3.5 text-tertiary" strokeWidth={1.5} />
          )}
          <span>Alert Feed</span>
          {unreadCount > 0 && (
            <span className="px-1.5 py-0.5 rounded text-2xs bg-gov-yellow-muted text-gov-yellow font-mono border border-gov-yellow/20">
              {unreadCount}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {unreadCount > 0 && open && (
            <button
              type="button"
              onClick={e => { e.stopPropagation(); dismissAll() }}
              className="text-2xs text-tertiary hover:text-secondary transition-colors px-1 py-0.5 rounded hover:bg-panel"
            >
              Dismiss all
            </button>
          )}
          <span className={`transition-transform duration-200 ${open ? 'rotate-180' : ''}`}>▾</span>
        </div>
      </button>

      {open && (
        <div className="max-h-72 overflow-y-auto">
          {visibleAlerts.length === 0 ? (
            <div className="px-4 py-8 text-xs text-tertiary text-center">
              No recent alerts
            </div>
          ) : (
            <div className="divide-y divide-default/40">
              {visibleAlerts.map(alert => (
                <div key={alert.id} className="flex items-start gap-2 px-4 py-2 hover:bg-panel/30 transition-colors group">
                  <div className="shrink-0 mt-0.5">
                    {severityIcon(alert.severity)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 text-xs">
                      <span className="font-mono font-semibold text-primary text-2xs">{alert.asset}</span>
                      <span className="text-2xs text-tertiary">{alert.message}</span>
                    </div>
                    <div className="text-2xs text-muted font-mono mt-0.5">
                      {formatAlertTime(alert.ts)}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => dismiss(alert.id)}
                    className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded hover:bg-panel text-muted hover:text-secondary"
                  >
                    <X className="w-2.5 h-2.5" strokeWidth={2} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}
