import type { AssetState } from '../types/portfolio'
import { ASSET_LABEL_PARAMS, LABEL_HORIZON } from '../lib/registry'

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

type StateClass = 'GREEN' | 'YELLOW' | 'RED' | 'INIT'

function classifyCalibration(prematureRate: number | null): StateClass {
  if (prematureRate === null) return 'INIT'
  if (prematureRate > 0.3) return 'RED'
  if (prematureRate > 0.1) return 'YELLOW'
  return 'GREEN'
}

interface GovernanceRowProps {
  asset: string
  state: AssetState
}

const stateColors: Record<StateClass, string> = {
  GREEN: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  YELLOW: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  RED: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
  INIT: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
}

function metaBand(decision?: string): string {
  if (decision === 'FULL') return 'FULL'
  if (decision === 'REDUCED') return 'REDUCED'
  if (decision === 'SKIP') return 'SKIP'
  return '—'
}

const labelVsRunColor = (labelSl: number, runtimeSl: number): string => {
  const gap = Math.abs(runtimeSl - labelSl)
  if (gap > 0.5) return 'text-amber-400'
  if (gap > 0.1) return 'text-slate-400'
  return 'text-emerald-400'
}

export default function GovernanceRow({ asset, state }: GovernanceRowProps) {
  const label = ASSET_LABEL_PARAMS[asset]
  if (!label) return null

  const runtimeSl = state.sl_mult ?? 0
  const runtimeTp = state.tp_mult ?? 0
  const prematureRate = computePrematureStopRate(state)
  const classification = classifyCalibration(prematureRate)

  return (
    <div className="border border-slate-800 bg-slate-900/50 p-4 rounded-xl font-mono text-xs text-slate-300">
      <div className="flex items-center justify-between mb-3 border-b border-slate-800 pb-2">
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold text-white">{asset}</span>
          <span className={`px-2 py-0.5 rounded border ${stateColors[classification]}`}>
            {classification}
          </span>
        </div>
        <div className="text-slate-500">
          Exposure:{' '}
          <span className="text-white">
            {state.validity_exposure != null ? state.validity_exposure.toFixed(2) : '—'}x
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <div className="flex justify-between">
            <span>Jaccard (10d):</span>
            <span className={state.feature_stability_jaccard != null ? 'text-indigo-400' : 'text-slate-500'}>
              {state.feature_stability_jaccard?.toFixed(2) ?? '—'}
            </span>
          </div>
          <div className="flex justify-between">
            <span>Meta-Model:</span>
            <span className="text-white">
              {metaBand(state.meta_decision)} (p={state.meta_confidence?.toFixed(2) ?? '—'})
            </span>
          </div>
        </div>

        <div className="space-y-1.5 border-l border-slate-800 pl-4">
          <div className="flex justify-between">
            <span>Label vs Run Exits:</span>
            <span className={labelVsRunColor(label.sl, runtimeSl)}>
              [{label.sl}/{label.pt}] vs [{runtimeSl.toFixed(2)}/{runtimeTp.toFixed(2)}]
            </span>
          </div>
          <div className="flex justify-between">
            <span>Premature Stops:</span>
            <span
              className={
                prematureRate == null
                  ? 'text-slate-500'
                  : prematureRate > 0.3
                    ? 'text-rose-400 font-bold'
                    : prematureRate > 0.1
                      ? 'text-amber-400'
                      : 'text-emerald-400'
              }
            >
              {prematureRate != null ? `${(prematureRate * 100).toFixed(1)}%` : '—'}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
