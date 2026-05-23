import type { AssetState } from '../types/portfolio'
import { ASSET_LABEL_PARAMS, LABEL_HORIZON } from '../lib/registry'
import StatusBadge from './ui/StatusBadge'
import {
  prematureRateState,
  governanceText,
  type GovernanceState,
} from './ui/governance'

function computePrematureStopRate(state: AssetState): number | null {
  const logs = state.metrics?.trade_log ?? []
  if (logs.length === 0) return null
  const premature = logs.filter(
    t =>
      (t.reason === 'sl' || t.reason === 'stop_loss' || t.reason === 'sl_hit') &&
      t.bars != null &&
      t.bars < LABEL_HORIZON,
  )
  return premature.length / logs.length
}

interface GovernanceRowProps {
  asset: string
  state: AssetState
}

function metaBand(decision?: string): string {
  if (decision === 'FULL') return 'FULL'
  if (decision === 'REDUCED') return 'REDUCED'
  if (decision === 'SKIP') return 'SKIP'
  return '—'
}

const labelVsRunColor = (labelSl: number, runtimeSl: number): string => {
  const gap = Math.abs(runtimeSl - labelSl)
  if (gap > 0.5) return 'text-gov-yellow'
  if (gap > 0.1) return 'text-secondary'
  return 'text-gov-green'
}

export default function GovernanceRow({ asset, state }: GovernanceRowProps) {
  const label = ASSET_LABEL_PARAMS[asset]
  if (!label) return null

  const runtimeSl = state.sl_mult ?? 0
  const runtimeTp = state.tp_mult ?? 0
  const prematureRate = computePrematureStopRate(state)
  const classification: GovernanceState = prematureRateState(prematureRate)

  return (
    <div className="bg-panel/80 border border-default rounded-lg px-3 py-2.5 text-[11px] text-secondary hover:border-strong/80 transition-colors">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-primary font-mono">{asset}</span>
          <StatusBadge state={classification} />
        </div>
        <span className="text-tertiary">
          Exposure{' '}
          <span className="font-mono text-primary tabular-nums">
            {state.validity_exposure != null ? `${state.validity_exposure.toFixed(2)}x` : '—'}
          </span>
        </span>
      </div>

      <div className="flex flex-wrap gap-x-5 gap-y-1.5 font-mono text-2xs sm:text-[11px]">
        <div>
          <span className="text-tertiary font-sans">Jaccard (10d) </span>
          <span className={state.feature_stability_jaccard != null ? 'text-accent-indigo' : 'text-muted'}>
            {state.feature_stability_jaccard?.toFixed(2) ?? '—'}
          </span>
        </div>
        <div>
          <span className="text-tertiary font-sans">Meta </span>
          <span className="text-primary">{metaBand(state.meta_decision)}</span>
          <span className="text-muted ml-0.5">(p={state.meta_confidence?.toFixed(2) ?? '—'})</span>
        </div>
        <div>
          <span className="text-tertiary font-sans">Label/Run </span>
          <span className={labelVsRunColor(label.sl, runtimeSl)}>
            [{label.sl}/{label.pt}] / [{runtimeSl.toFixed(2)}/{runtimeTp.toFixed(2)}]
          </span>
        </div>
        <div>
          <span className="text-tertiary font-sans">Premature </span>
          <span
            className={
              prematureRate == null
                ? 'text-muted'
                : governanceText[prematureRateState(prematureRate)] + (prematureRate > 0.3 ? ' font-semibold' : '')
            }
          >
            {prematureRate != null ? `${(prematureRate * 100).toFixed(1)}%` : '—'}
          </span>
        </div>
      </div>
    </div>
  )
}
