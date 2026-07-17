import { useState } from 'react'
import { X, Clock, BarChart3, GitCompare, Shield } from 'lucide-react'
import { useTradeInspector } from '../../hooks/useTradeInspector'
import TradeTimeline from './TradeTimeline'
import TradeGovernanceAudit from './TradeGovernanceAudit'
import TradeCounterfactual from './TradeCounterfactual'
import { computeDomainScores } from '../attribution/domainScores'
import { Skeleton } from '../ui/Skeleton'
import { BarRow } from '../ui/ProgressBar'
import Modal from '../ui/Modal'
import Tabs, { TabPanel } from '../ui/Tabs'

interface TradeInspectorModalProps {
  asset: string
  entryDate: string
  exitDate?: string
  onClose: () => void
}

type TabId = 'timeline' | 'attribution' | 'counterfactual' | 'governance'

const TABS: { id: TabId; label: string; icon: React.ReactNode }[] = [
  { id: 'timeline', label: 'Timeline', icon: <Clock className="w-3 h-3" strokeWidth={1.5} /> },
  { id: 'attribution', label: 'Attribution', icon: <BarChart3 className="w-3 h-3" strokeWidth={1.5} /> },
  { id: 'counterfactual', label: 'Counterfactual', icon: <GitCompare className="w-3 h-3" strokeWidth={1.5} /> },
  { id: 'governance', label: 'Governance', icon: <Shield className="w-3 h-3" strokeWidth={1.5} /> },
]

/** Full-screen modal for inspecting a single trade across timeline, attribution, counterfactual, and governance tabs. */
export default function TradeInspectorModal({ asset, entryDate, exitDate, onClose }: TradeInspectorModalProps) {
  const [tab, setTab] = useState<TabId>('timeline')
  const tradeData = useTradeInspector(asset, entryDate, exitDate)

  const attribution = tradeData?.attribution

  return (
    <Modal open onClose={onClose} size="lg" noContentWrap>
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-default shrink-0">
          <div>
            <h2 className="text-sm font-semibold text-primary">
              {asset} · {tradeData?.basic.side?.toUpperCase() ?? '—'}
            </h2>
            <p className="text-2xs text-tertiary font-mono mt-0.5">
              {entryDate} → {exitDate ?? '—'}
            </p>
          </div>
          <button
            onClick={onClose}
            className="min-h-[36px] min-w-[36px] inline-flex items-center justify-center rounded-md hover:bg-panel border border-transparent hover:border-default transition-colors"
          >
            <X className="w-3.5 h-3.5 text-tertiary" strokeWidth={2} />
          </button>
        </div>

        {/* Tabs using canonical Tabs component — generic type inferred from TABS */}
        <Tabs tabs={TABS} activeTab={tab} onTabChange={setTab} size="sm" />

        {/* Content using TabPanel for proper ARIA */}
        <div className="flex-1 overflow-y-auto p-4">
          {!attribution ? (
            <div className="space-y-3">
              <Skeleton className="h-20 rounded-lg" />
              <Skeleton className="h-32 rounded-lg" />
              <Skeleton className="h-24 rounded-lg" />
            </div>
          ) : (
            <>
              <TabPanel id="timeline" active={tab === 'timeline'}>
                <TradeTimeline data={attribution} />
              </TabPanel>
              <TabPanel id="attribution" active={tab === 'attribution'}>
                <div className="space-y-4">
                  {(() => {
                    const scores = computeDomainScores(attribution)
                    return (
                      <>
                        <div className="space-y-2">
                          <p className="text-2xs font-semibold text-tertiary uppercase tracking-wider mb-2">Domain Scores</p>
                          <BarRow label="Prediction" value={scores.prediction_score} color="var(--color-accent-blue)" cssColor />
                          <BarRow label="Execution" value={scores.execution_score} color="var(--color-accent-purple)" cssColor />
                          <BarRow label="Exit" value={scores.exit_score} color="var(--color-gov-green)" cssColor />
                          <BarRow label="Friction" value={scores.friction_score} color="var(--color-accent-amber)" cssColor />
                        </div>

                        <div className="grid grid-cols-2 gap-3 pt-3 border-t border-default">
                          <div className="space-y-1">
                            <p className="text-2xs text-tertiary">Signal</p>
                            <p className="text-xs font-mono text-primary">{attribution.pred_signal}</p>
                          </div>
                          <div className="space-y-1">
                            <p className="text-2xs text-tertiary">Confidence</p>
                            <p className="text-xs font-mono text-primary">{(attribution.pred_confidence * 100).toFixed(0)}%</p>
                          </div>
                          <div className="space-y-1">
                            <p className="text-2xs text-tertiary">Realized R</p>
                            <p className={`text-xs font-mono font-bold ${attribution.exit_realized_r >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
                              {attribution.exit_realized_r.toFixed(2)}
                            </p>
                          </div>
                          <div className="space-y-1">
                            <p className="text-2xs text-tertiary">Exit Reason</p>
                            <p className="text-xs font-mono text-primary">{attribution.exit_exit_reason}</p>
                          </div>
                        </div>
                      </>
                    )
                  })()}
                </div>
              </TabPanel>
              <TabPanel id="counterfactual" active={tab === 'counterfactual'}>
                <TradeCounterfactual data={attribution} />
              </TabPanel>
              <TabPanel id="governance" active={tab === 'governance'}>
                <TradeGovernanceAudit data={attribution} />
              </TabPanel>
            </>
          )}
        </div>

        {/* Footer */}
        {attribution && (
          <div className="flex items-center justify-between px-4 py-2 border-t border-default bg-surface/50 text-2xs text-tertiary shrink-0 rounded-b-xl">
            <span>Trade #{attribution.trade_id}</span>
            <span>PnL: <span className={attribution.realized_pnl >= 0 ? 'text-gov-green' : 'text-gov-red'}>
              {attribution.realized_pnl >= 0 ? '+' : ''}{attribution.realized_pnl.toFixed(2)}
            </span></span>
          </div>
        )}
      </div>
    </Modal>
  )
}
