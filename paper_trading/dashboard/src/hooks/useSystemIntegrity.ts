import { useMemo } from 'react'
import type { SystemBundle } from '../types/bundle'

export interface SystemIntegrity {
  /** Bundle fetched and status is 'ok' */
  isHealthy: boolean
  /** Any live source is stale but snapshot is valid */
  isDegraded: boolean
  /** Snapshot itself failed — cannot render safely */
  isBroken: boolean
  /** At least one live source (health, mt5) is stale */
  hasStaleLive: boolean
  /** true when render should be blocked entirely */
  shouldBlockRender: boolean
  /** Human label for display in header / degraded banner */
  label: 'healthy' | 'degraded' | 'partial_failure' | 'no_data'
  /** Specific stale source names for targeted messaging */
  staleSources: string[]
}

const INITIAL: SystemIntegrity = {
  isHealthy: false,
  isDegraded: false,
  isBroken: false,
  hasStaleLive: false,
  shouldBlockRender: true,
  label: 'no_data',
  staleSources: [],
} as const

/** Derives system integrity status (healthy/degraded/broken) from the snapshot bundle. @returns {SystemIntegrity} - Integrity assessment with label and stale sources */
export function useSystemIntegrity(bundle: SystemBundle | undefined): SystemIntegrity {
  return useMemo(() => {
    if (!bundle?.meta) return INITIAL

    const meta = bundle.meta
    const status = meta.status

    const healthFresh = bundle.live?.health?.is_fresh !== false
    const mt5Fresh = bundle.live?.mt5?.is_fresh !== false
    const hasStaleLive = !healthFresh || !mt5Fresh

    const staleSources: string[] = []
    if (!healthFresh) staleSources.push('health')
    if (!mt5Fresh) staleSources.push('MT5')

    const isBroken = status === 'partial_failure'
    const isDegraded = status === 'degraded' || hasStaleLive

    return {
      isHealthy: status === 'ok' && !hasStaleLive,
      isDegraded,
      isBroken,
      hasStaleLive,
      shouldBlockRender: isBroken,
      label: isBroken ? 'partial_failure' : isDegraded ? 'degraded' : 'healthy',
      staleSources,
    }
  }, [bundle])
}
