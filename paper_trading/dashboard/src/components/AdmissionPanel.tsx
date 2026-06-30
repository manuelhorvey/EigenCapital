import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import Panel from './ui/Panel'
import { Skeleton } from './ui/Skeleton'

function pctColor(ratio: number): string {
  if (ratio > 0.8) return 'var(--color-gov-red)'
  if (ratio > 0.5) return 'var(--color-gov-yellow)'
  return 'var(--color-gov-green)'
}

export default function AdmissionPanel() {
  const { data: portfolio } = useSystemSnapshot(systemSelectors.portfolio)
  const adm = portfolio?.admission

  if (!adm) return <Panel padding="md"><Skeleton className="h-16 rounded" shimmer /></Panel>

  const admittedPct = adm.n_intents > 0 ? adm.n_admitted / adm.n_intents : 0
  const rejectedPct = adm.n_intents > 0 ? adm.n_rejected / adm.n_intents : 0

  return (
    <Panel padding="md">
      <div className="space-y-2">
        <span className="text-2xs text-tertiary font-medium uppercase tracking-wider">PEK Admission</span>

        <div className="grid grid-cols-3 gap-2 text-center">
          <div>
            <div className="text-lg font-bold font-mono tabular-nums text-primary">{adm.n_intents}</div>
            <div className="text-2xs text-tertiary">Intents</div>
          </div>
          <div>
            <div className="text-lg font-bold font-mono tabular-nums" style={{ color: pctColor(admittedPct) }}>
              {adm.n_admitted}
            </div>
            <div className="text-2xs text-tertiary">Admitted</div>
          </div>
          <div>
            <div className="text-lg font-bold font-mono tabular-nums" style={{ color: pctColor(rejectedPct) }}>
              {adm.n_rejected}
            </div>
            <div className="text-2xs text-tertiary">Rejected</div>
          </div>
        </div>

        <div className="text-2xs text-tertiary font-mono">
          Budget notional: ${(adm.budget_notional ?? 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
        </div>

        {adm.admitted && adm.admitted.length > 0 && (
          <div className="text-2xs text-tertiary">
            <span className="font-medium text-gov-green/80">Admitted: </span>
            {adm.admitted.join(', ')}
          </div>
        )}

        {adm.rejected && adm.rejected.length > 0 && (
          <div className="text-2xs text-tertiary">
            <span className="font-medium text-gov-red/80">Rejected: </span>
            <span className="text-gov-red/60">{adm.rejected.join(', ')}</span>
          </div>
        )}
      </div>
    </Panel>
  )
}
