import { memo } from 'react'
import { useTradingState } from '../lib/trading-state/hook'
import { useWidgetVisibility } from '../hooks/useWidgetVisibility'
import ErrorBoundary from '../components/ErrorBoundary'
import SystemHealthSummary from '../components/SystemHealthSummary'
import QuickStatsGrid from '../components/QuickStatsGrid'
import EdgeHealthAlert from '../components/EdgeHealthAlert'
import OptimizerRecommendations from '../components/OptimizerRecommendations'
import HaltConditions from '../components/HaltConditions'
import EquityCurveWithRange from '../components/EquityCurveWithRange'
import AssetMiniGrid from '../components/AssetMiniGrid'
import AssetListPanel from '../components/AssetListPanel'
import SystemStatusBar from '../components/SystemStatusBar'
import { EntranceAnimator, Stagger } from '../components/ui'
import { AlertTriangle } from 'lucide-react'
import { SECTION_SPACING, GRID_GAP, gridSplit2 } from '../design/grid'

interface CommandCenterProps {
  onSelectAsset?: (name: string) => void
}

const CommandCenter = memo(function CommandCenter({ onSelectAsset }: CommandCenterProps) {
  const { portfolio } = useTradingState()
  const { isVisible } = useWidgetVisibility()
  const showEdgeWarning = portfolio?.alpha?.edge_trend === 'DECAYING'

  return (
    <div className={SECTION_SPACING}>
      {isVisible('system-status') && (
        <EntranceAnimator variant="fade-in">
          <SystemStatusBar />
        </EntranceAnimator>
      )}

      {isVisible('system-health') && (
        <ErrorBoundary title="System Health">
          <SystemHealthSummary />
        </ErrorBoundary>
      )}

      {isVisible('quick-stats') && (
        <ErrorBoundary title="Quick Stats">
          <QuickStatsGrid />
        </ErrorBoundary>
      )}

      {isVisible('equity-curve') && (
        <ErrorBoundary title="Equity & Edge Health">
          <div className={`grid-cols-1 lg:grid-cols-3 ${GRID_GAP} grid`}>
            <div className="lg:col-span-2 2xl:col-span-2">
              <EquityCurveWithRange />
            </div>
            <div>
              <EdgeHealthAlert />
            </div>
          </div>
        </ErrorBoundary>
      )}

      <Stagger staggerMs={30} initialDelay={15}>
        {isVisible('open-positions') && (
          <ErrorBoundary title="Open Positions">
            <EntranceAnimator variant="fade-up">
              <AssetMiniGrid openOnly />
            </EntranceAnimator>
          </ErrorBoundary>
        )}

        {isVisible('positions-list') && (
          <ErrorBoundary title="Positions List">
            <EntranceAnimator variant="fade-up">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-medium text-tertiary uppercase tracking-wider">Positions</span>
                {showEdgeWarning && (
                  <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-signal-warn/10 border border-signal-warn/20 text-[10px] text-signal-warn">
                    <AlertTriangle className="w-3 h-3" strokeWidth={2} />
                    Edge decaying — monitor reversals
                  </div>
                )}
              </div>
              <AssetListPanel onSelectAsset={onSelectAsset} />
            </EntranceAnimator>
          </ErrorBoundary>
        )}

        {(isVisible('risk-signals') || isVisible('optimizer')) && (
          <ErrorBoundary title="Risk & Optimizer">
            <div className={`${gridSplit2(true)} ${GRID_GAP}`}>
              {isVisible('risk-signals') && (
                <EntranceAnimator variant="fade-up">
                  <div className="space-y-2">
                    <span className="text-xs text-tertiary font-medium uppercase tracking-wider">Risk Signals</span>
                    <HaltConditions />
                  </div>
                </EntranceAnimator>
              )}
              {isVisible('optimizer') && (
                <EntranceAnimator variant="fade-up">
                  <div className="space-y-2">
                    <span className="text-xs text-tertiary font-medium uppercase tracking-wider">Optimizer</span>
                    <OptimizerRecommendations />
                  </div>
                </EntranceAnimator>
              )}
            </div>
          </ErrorBoundary>
        )}
      </Stagger>
    </div>
  )
})
CommandCenter.displayName = 'CommandCenter'

export default CommandCenter
