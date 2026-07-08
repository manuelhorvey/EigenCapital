import { memo } from 'react'
import { useTradingState } from '../lib/trading-state/hook'
import ErrorBoundary from '../components/ErrorBoundary'
import SystemHealthSummary from '../components/SystemHealthSummary'
import QuickStatsGrid from '../components/QuickStatsGrid'
import EdgeHealthAlert from '../components/EdgeHealthAlert'
import LiveSharpeCard from '../components/LiveSharpeCard'
import OptimizerRecommendations from '../components/OptimizerRecommendations'
import HaltConditions from '../components/HaltConditions'
import EquityCurveSparkline from '../components/EquityCurveSparkline'
import AssetMiniGrid from '../components/AssetMiniGrid'
import AssetListPanel from '../components/AssetListPanel'
import Panel from '../components/ui/Panel'
import EntranceAnimator from '../components/ui/EntranceAnimator'
import { AlertTriangle } from 'lucide-react'

// ── Live Sharpe Panel ──────────────────────────────────────────────

const LiveSharpePanel = memo(function LiveSharpePanel() {
  return (
    <EntranceAnimator variant="fade-up" delay={210}>
      <div className="space-y-2">
        <span className="text-xs text-tertiary font-medium uppercase tracking-wider">Live Sharpe</span>
        <LiveSharpeCard />
      </div>
    </EntranceAnimator>
  )
})

// ── AssetListPanel ────────────────────────────────────────────────

// Moved to /src/components/AssetListPanel.tsx as a standalone memo'd
// component (Commit 3.2 extraction).

// ── Main Page ──────────────────────────────────────────────────────

interface CommandCenterProps {
  onSelectAsset?: (name: string) => void
}

const CommandCenter = memo(function CommandCenter({ onSelectAsset }: CommandCenterProps) {
  const { portfolio } = useTradingState()
  const showEdgeWarning = portfolio?.alpha?.edge_trend === 'DECAYING'

  return (
    <div className="space-y-6 sm:space-y-8">
      {/* Emergency banner is rendered once at the AppShell level (above) */}
      {/* System health — single source of truth */}
      <ErrorBoundary title="System Health">
        <SystemHealthSummary />
      </ErrorBoundary>

      {/* Quick stats row */}
      <ErrorBoundary title="Quick Stats">
        <QuickStatsGrid />
      </ErrorBoundary>

      {/* Equity curve + edge health */}
      <ErrorBoundary title="Equity & Edge Health">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2">
            <Panel padding="md">
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-medium text-tertiary uppercase tracking-wider">Equity Curve</span>
              </div>
              <div className="w-full">
                <EquityCurveSparkline height={200} />
              </div>
            </Panel>
          </div>
          <div>
            <EdgeHealthAlert />
          </div>
        </div>
      </ErrorBoundary>

      {/* Asset cards grid — open positions only */}
      <ErrorBoundary title="Open Positions">
        <EntranceAnimator variant="fade-up" delay={45}>
          <AssetMiniGrid openOnly />
        </EntranceAnimator>
      </ErrorBoundary>

      {/* Asset list with sort controls — main trading view */}
      <ErrorBoundary title="Positions List">
        <EntranceAnimator variant="fade-up" delay={60}>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-medium text-tertiary uppercase tracking-wider">Positions</span>
            {showEdgeWarning && (
              <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-gov-yellow/10 border border-gov-yellow/20 text-[10px] text-gov-yellow">
                <AlertTriangle className="w-3 h-3" strokeWidth={2} />
                Edge decaying — monitor reversals
              </div>
            )}
          </div>
          <AssetListPanel onSelectAsset={onSelectAsset} />
        </EntranceAnimator>
      </ErrorBoundary>

      {/* Risk signals + optimizer */}
      <ErrorBoundary title="Risk & Optimizer">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <EntranceAnimator variant="fade-up" delay={120}>
            <div className="space-y-2">
              <span className="text-xs text-tertiary font-medium uppercase tracking-wider">Risk Signals</span>
              <HaltConditions />
            </div>
          </EntranceAnimator>
          <EntranceAnimator variant="fade-up" delay={180}>
            <div className="space-y-2">
              <span className="text-xs text-tertiary font-medium uppercase tracking-wider">Optimizer</span>
              <OptimizerRecommendations />
            </div>
          </EntranceAnimator>
        </div>
      </ErrorBoundary>

      {/* Live sharpe */}
      <ErrorBoundary title="Live Sharpe">
        <LiveSharpePanel />
      </ErrorBoundary>
    </div>
  )
})

export default CommandCenter
