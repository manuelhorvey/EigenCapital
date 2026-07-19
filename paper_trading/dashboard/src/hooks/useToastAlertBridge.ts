import { useEffect, useRef } from 'react'
import { useMonitorAlerts } from './useMonitorAlerts'
import { useEngineHealth } from './useEngineHealth'
import { useToast } from './useToast'
import { useNotificationCenter } from './useNotificationCenter'
import { useBrowserNotifications, notifTag } from './useBrowserNotifications'
import { useSystemSnapshot } from './useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import { playAlertSound } from './useSoundAlerts'

/**
 * Connects the passive alert/monitoring systems to the real-time
 * notification channels:
 *   monitor alerts → toast + notification history + desktop notification
 *   engine health  → toast + notification history + desktop notification
 *   PEK rejections → toast + notification history + desktop notification
 */
export function useToastAlertBridge() {
  const { add: addNotification } = useNotificationCenter()
  const { notify: browserNotify } = useBrowserNotifications()
  const alerts = useMonitorAlerts()
  const { toast } = useToast()
  const previousAlertIds = useRef<Set<string>>(new Set())

  // ── Monitor alerts ────────────────────────────────────────────
  useEffect(() => {
    const currentIds = new Set(alerts.map(a => a.id))
    for (const alert of alerts) {
      if (!previousAlertIds.current.has(alert.id)) {
        const nType = alert.severity === 'critical' ? 'error' : 'warning'
        toast({
          type: nType,
          title: alert.message,
          message: alert.detail ?? undefined,
          duration: alert.severity === 'critical' ? 6000 : 4000,
        })
        addNotification({
          type: nType,
          title: alert.message,
          message: alert.detail ?? undefined,
        })
        if (alert.severity === 'critical') {
          browserNotify({
            title: alert.message,
            body: alert.detail ?? undefined,
            tag: notifTag(`alert-${alert.id}`),
            force: true,
          })
          playAlertSound()
        }
      }
    }
    previousAlertIds.current = currentIds
  }, [alerts, toast, addNotification, browserNotify])

  // ── Engine health ─────────────────────────────────────────────
  const health = useEngineHealth()
  const previousEngineDead = useRef(false)

  useEffect(() => {
    const isDead = !!(health.isError || (health.data && !health.data.engine_alive))
    if (isDead && !previousEngineDead.current) {
      toast({
        type: 'error',
        title: 'Engine connection lost',
        message: 'Dashboard data may be stale',
        duration: 0,
      })
      addNotification({
        type: 'error',
        title: 'Engine connection lost',
        message: 'Dashboard data may be stale',
      })
      browserNotify({
        title: 'Engine connection lost',
        body: 'Dashboard data may be stale. The trading engine may have stopped.',
        tag: notifTag('engine-lost'),
        force: true,
      })
      playAlertSound()
    } else if (!isDead && previousEngineDead.current) {
      toast({
        type: 'success',
        title: 'Engine reconnected',
        duration: 3000,
      })
      addNotification({
        type: 'success',
        title: 'Engine reconnected',
      })
      browserNotify({
        title: 'Engine reconnected',
        body: 'The trading engine is alive and reporting health checks again.',
        tag: notifTag('engine-reconnect'),
      })
    }
    previousEngineDead.current = isDead
  }, [health, toast, addNotification, browserNotify])

  // ── PEK admission rejections ──────────────────────────────────
  const { data: bundlem } = useSystemSnapshot(systemSelectors.portfolio)
  const admission = bundlem?.admission
  const prevRejectedAssets = useRef<string[]>([])

  useEffect(() => {
    if (!admission) return
    const currentRejected = admission.rejected ?? []
    const prevSet = new Set(prevRejectedAssets.current)
    const newRejections = currentRejected.filter(a => !prevSet.has(a))
    for (const asset of newRejections) {
      const reason = admission.rejection_reasons?.[asset] ?? 'PEK budget/rank limit'

      toast({
        type: 'warning',
        title: `${asset} signal rejected`,
        message: reason,
        duration: 5000,
      })
      addNotification({
        type: 'warning',
        title: `${asset} signal rejected`,
        message: reason,
      })
      browserNotify({
        title: `${asset} signal rejected`,
        body: reason,
        tag: notifTag(`rejection-${asset}`),
      })
    }
    prevRejectedAssets.current = currentRejected
  }, [admission, toast, addNotification, browserNotify])
}
