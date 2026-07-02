import type { BadgeVariant } from '../../components/ui/Badge'

type GovernanceStatus = 'pass' | 'warn' | 'fail' | 'healthy' | 'warning' | 'critical' | 'unknown' | 'SAFE' | 'MONITOR' | 'ALERT'

interface BadgeConfig {
  variant: BadgeVariant
  label: string
}

export function toBadgeConfig(status: GovernanceStatus): BadgeConfig {
  switch (status) {
    case 'SAFE':
      return { variant: 'success', label: 'SAFE' }
    case 'MONITOR':
      return { variant: 'warning', label: 'MONITOR' }
    case 'ALERT':
      return { variant: 'error', label: 'ALERT' }
    case 'pass':
    case 'healthy':
      return { variant: 'success', label: 'OK' }
    case 'warn':
    case 'warning':
      return { variant: 'warning', label: 'WARN' }
    case 'fail':
    case 'critical':
      return { variant: 'error', label: 'FAIL' }
    case 'unknown':
      return { variant: 'neutral', label: 'N/A' }
  }
}
