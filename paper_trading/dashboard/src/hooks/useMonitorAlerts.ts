import { useEffect, useMemo, useState } from 'react'
import { useSystemSnapshot } from './useSystemSnapshot'

const ALERTS_CHANNEL = 'quorrin-alerts'

let _channel: BroadcastChannel | null = null
function getChannel(): BroadcastChannel {
  if (typeof BroadcastChannel === 'undefined') return null as never
  if (!_channel) _channel = new BroadcastChannel(ALERTS_CHANNEL)
  return _channel
}

export interface Alert {
  id: string
  type: 'health' | 'halt' | 'governance' | 'performance'
  asset: string
  severity: 'critical' | 'warning' | 'info'
  message: string
  detail?: string
  count?: number
  assets?: string[]
  timestamp: string
}

let _dismissedVersion = ''

export function setDismissedVersion(version: string) {
  _dismissedVersion = version
}

function dismissedKey(): string {
  return _dismissedVersion ? `qf-dismissed-alerts-${_dismissedVersion}` : 'qf-dismissed-alerts'
}

function loadDismissed(): Set<string> {
  try {
    const raw = sessionStorage.getItem(dismissedKey())
    return new Set(raw ? JSON.parse(raw) : [])
  } catch {
    return new Set()
  }
}

export function dismissAlert(id: string) {
  const key = dismissedKey()
  const dismissed = loadDismissed()
  dismissed.add(id)
  try {
    sessionStorage.setItem(key, JSON.stringify([...dismissed]))
    const ch = getChannel()
    if (ch) ch.postMessage({ type: 'dismiss', id })
  } catch {}
}

function shortenMessage(msg: string): string {
  return msg.replace(/sl=\d+\.\d+x size=\d+\.\d+x/g, '').replace(/,\s*,/g, ',').replace(/,\s*$/, '').trim()
}

export function useMonitorAlerts(): Alert[] {
  const { data: bundle } = useSystemSnapshot()
  const state = bundle?.snapshot
  const health = bundle?.live?.health
  const seqId = bundle?.meta?.snapshot_sequence_id
  const [broadcastTick, setBroadcastTick] = useState(0)

  useEffect(() => {
    if (bundle?.meta?.version) setDismissedVersion(bundle.meta.version)
  }, [bundle?.meta?.version])

  useEffect(() => {
    const ch = getChannel()
    if (!ch) return
    const handler = (e: MessageEvent) => {
      if (e.data?.type === 'dismiss' && e.data?.id) {
        const dismissed = loadDismissed()
        dismissed.add(e.data.id)
        try {
          sessionStorage.setItem(dismissedKey(), JSON.stringify([...dismissed]))
        } catch {}
        setBroadcastTick(t => t + 1)
      }
    }
    ch.addEventListener('message', handler)
    return () => ch.removeEventListener('message', handler)
  }, [])

  return useMemo(() => {
    const alerts: Alert[] = []
    const dismissed = loadDismissed()
    const now = state?.timestamp ?? new Date().toISOString()

    // Group halted assets by reason
    const haltByReason = new Map<string, string[]>()
    if (state?.assets) {
      for (const [name, asset] of Object.entries(state.assets)) {
        if (asset.halt?.halted) {
          const reasons = asset.halt.reasons ?? ['unknown']
          const key = reasons.join('; ')
          if (!haltByReason.has(key)) haltByReason.set(key, [])
          haltByReason.get(key)!.push(name)
        }
      }
    }

    for (const [reasonKey, assets] of haltByReason) {
      const short = shortenMessage(reasonKey)
      alerts.push({
        id: `halt-${reasonKey.slice(0, 20).replace(/\s+/g, '-')}`,
        type: 'halt',
        asset: assets.length === 1 ? assets[0] : `${assets.length} assets`,
        severity: 'critical',
        message: assets.length === 1
          ? `${assets[0]} halted — ${short}`
          : `${assets.length} assets halted — ${short}`,
        detail: assets.join(', '),
        count: assets.length,
        assets,
        timestamp: now,
      })
    }

    // Group health alerts by label
    const healthCritical: string[] = []
    const healthDegraded: string[] = []
    if (health?.assets) {
      for (const [name, h] of Object.entries(health.assets)) {
        if (h.health_score < 0.5) healthCritical.push(name)
        else if (h.health_score < 0.8) healthDegraded.push(name)
      }
    }

    if (healthCritical.length > 0) {
      alerts.push({
        id: 'health-critical',
        type: 'health',
        asset: healthCritical.length === 1 ? healthCritical[0] : `${healthCritical.length} assets`,
        severity: 'critical',
        message: healthCritical.length === 1
          ? `${healthCritical[0]} health critical`
          : `${healthCritical.length} assets health critical`,
        detail: healthCritical.join(', '),
        count: healthCritical.length,
        assets: healthCritical,
        timestamp: now,
      })
    }

    if (healthDegraded.length > 0) {
      alerts.push({
        id: 'health-degraded',
        type: 'health',
        asset: healthDegraded.length === 1 ? healthDegraded[0] : `${healthDegraded.length} assets`,
        severity: 'warning',
        message: healthDegraded.length === 1
          ? `${healthDegraded[0]} health degraded`
          : `${healthDegraded.length} assets health degraded`,
        detail: healthDegraded.join(', '),
        count: healthDegraded.length,
        assets: healthDegraded,
        timestamp: now,
      })
    }

    // Governance alerts from halt thresholds
    if (state?.halt_conditions) {
      const hc = state.halt_conditions
      if (hc.drawdown > 0.15) {
        alerts.push({
          id: 'gov-drawdown',
          type: 'governance',
          asset: 'SYSTEM',
          severity: 'critical',
          message: `Portfolio drawdown threshold exceeded (${(hc.drawdown * 100).toFixed(1)}%)`,
          timestamp: now,
        })
      }
      if (hc.prob_drift > 0.3) {
        alerts.push({
          id: 'gov-psi',
          type: 'governance',
          asset: 'SYSTEM',
          severity: 'warning',
          message: `PSI drift elevated (${(hc.prob_drift * 100).toFixed(0)}%)`,
          timestamp: now,
        })
      }
    }

    return alerts.filter(a => !dismissed.has(a.id))
  }, [seqId, state, health, broadcastTick])
}
