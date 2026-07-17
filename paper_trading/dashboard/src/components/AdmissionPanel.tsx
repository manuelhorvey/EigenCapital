import { useSystemSnapshot } from '../hooks/useSystemSnapshot'
import { systemSelectors } from '../selectors/system'
import BudgetGauge from './BudgetGauge'
import Panel from './ui/Panel'
import { Skeleton } from './ui/Skeleton'

function pctColor(ratio: number): string {
  if (ratio > 0.8) return 'var(--color-gov-red)'
  if (ratio > 0.5) return 'var(--color-gov-yellow)'
  return 'var(--color-gov-green)'
}

/** PEK admission summary showing intents, admitted, rejected, and budget notional. */
export default function AdmissionPanel() {
  const { data: portfolio } = useSystemSnapshot(systemSelectors.portfolio)
  const adm = portfolio?.admission

  if (!adm) return <Panel padding="md"><Skeleton className="h-16 rounded" shimmer /></Panel>

  const admittedPct = adm.n_intents > 0 ? adm.n_admitted / adm.n_intents : 0
  const rejectedPct = adm.n_intents > 0 ? adm.n_rejected / adm.n_intents : 0

  return (
    <Panel padding="md">
      <div className="space-y-3">
        <span className="text-2xs text-tertiary font-medium uppercase tracking-wider">PEK Admission</span>

        <dl className="grid grid-cols-3 lg:divide-x lg:divide-default -mx-1">
          <div className="px-3 py-1 min-w-0">
            <dt className="text-2xs text-tertiary uppercase tracking-wider truncate">Intents</dt>
            <dd className="text-base font-bold font-mono tabular-nums text-primary">{adm.n_intents}</dd>
          </div>
          <div className="px-3 py-1 min-w-0">
            <dt className="text-2xs text-tertiary uppercase tracking-wider truncate">Admitted</dt>
            <dd className="text-base font-bold font-mono tabular-nums" style={{ color: pctColor(admittedPct) }}>{adm.n_admitted}</dd>
          </div>
          <div className="px-3 py-1 min-w-0">
            <dt className="text-2xs text-tertiary uppercase tracking-wider truncate">Rejected</dt>
            <dd className="text-base font-bold font-mono tabular-nums" style={{ color: pctColor(rejectedPct) }}>{adm.n_rejected}</dd>
          </div>
        </dl>

        <div className="pt-2 border-t border-default space-y-2">
          <div className="text-2xs text-tertiary font-mono">
            Budget notional: ${(adm.budget_notional ?? 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
          </div>
          <BudgetGauge utilization={portfolio?.pek_budget_utilization} />
        </div>

        {adm.admitted && adm.admitted.length > 0 && (
          <div className="text-2xs text-tertiary">
            <span className="font-medium text-gov-green/80">Admitted: </span>
            <span className="font-mono">{adm.admitted.join(', ')}</span>
          </div>
        )}

        {adm.rejected && adm.rejected.length > 0 && (
          <div className="text-2xs text-tertiary">
            <span className="font-medium text-gov-red/80">Rejected: </span>
            <span className="font-mono text-gov-red/70">{adm.rejected.join(', ')}</span>
          </div>
        )}
      </div>
    </Panel>
  )
}
