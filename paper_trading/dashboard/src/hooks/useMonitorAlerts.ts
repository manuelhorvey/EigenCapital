import { useEffect, useMemo, useRef, useState } from 'react'
import { useSystemSnapshot } from './useSystemSnapshot'
import { systemSelectors, selectMeta } from '../selectors/system'
import { addErrorBreadcrumb } from '../lib/errorReporting'

const ALERTS_CHANNEL = 'eigencapital-alerts'

let _dismissedVersionOverride: string | undefined

export function setDismissedVersion(v: string | undefined) {
  _dismissedVersionOverride = v
}

function makeChannel(): BroadcastChannel | null {
  if (typeof BroadcastChannel === 'undefined') return null
  return new BroadcastChannel(ALERTS_CHANNEL)
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

function _useVersion(version: string): string {
  return _dismissedVersionOverride !== undefined ? _dismissedVersionOverride : version
}

function dismissedKey(version: string): string {
  const v = _useVersion(version)
  return v ? `ec-dismissed-alerts-${v}` : 'ec-dismissed-alerts'
}

function loadDismissed(version: string): Set<string> {
  try {
    const raw = sessionStorage.getItem(dismissedKey(version))
    return new Set(raw ? JSON.parse(raw) : [])
  } catch {
    console.error('[Alerts] failed to load dismissed set from sessionStorage')
    addErrorBreadcrumb('Alerts', 'Failed to load dismissed set from sessionStorage')
    return new Set()
  }
}

function persistDismissed(id: string, version: string) {
  const key = dismissedKey(version)
  const dismissed = loadDismissed(version)
  dismissed.add(id)
  try {
    sessionStorage.setItem(key, JSON.stringify([...dismissed]))
  } catch {
    console.error('[Alerts] failed to persist dismissed alert to sessionStorage')
    addErrorBreadcrumb('Alerts', 'Failed to persist dismissed alert')
  }
}

export function dismissAlert(id: string) {
  persistDismissed(id, '')
  const ch = makeChannel()
  if (ch) {
    ch.postMessage({ type: 'dismiss', id })
    ch.close()
  }
}

function shortenMessage(msg: string): string {
  return msg.replace(/sl=\d+\.\d+x size=\d+\.\d+x/g, '').replace(/,\s*,/g, ',').replace(/,\s*$/, '').trim()
}

/** Derives active alerts from the system snapshot — halted assets, health critical/degraded, and governance threshold breaches. @returns {Alert[]} - Array of alert objects sorted by severity */
export function useMonitorAlerts(): Alert[] {
  const { data: snapshot } = useSystemSnapshot(systemSelectors.snapshot)
  const { data: health } = useSystemSnapshot(systemSelectors.health)
  const { data: meta } = useSystemSnapshot(selectMeta)
  const state = snapshot
  const seqId = snapshot?.sequence_id
  const [broadcastTick, setBroadcastTick] = useState(0)

  const versionRef = useRef('')
  const version = meta?.version ?? ''
  if (version && versionRef.current !== version) {
    versionRef.current = version
  }

  useEffect(() => {
    const ch = makeChannel()
    if (!ch) return
    const handler = (e: MessageEvent) => {
      if (e.data?.type === 'dismiss' && e.data?.id) {
        persistDismissed(e.data.id, versionRef.current)
        setBroadcastTick(t => t + 1)
      }
    }
    ch.addEventListener('message', handler)
    return () => {
      ch.removeEventListener('message', handler)
      ch.close()
    }
  }, [])

  return useMemo(() => {
    const v = versionRef.current
    const alerts: Alert[] = []
    const dismissed = loadDismissed(v)
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
