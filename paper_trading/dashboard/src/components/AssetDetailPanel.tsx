import { useState } from 'react'
import { X, Shield, Sliders, Activity, BarChart3, Clock, List } from 'lucide-react'
import type { z } from 'zod'
import { AssetStateSchema } from '../lib/schemas'

type AssetState = z.infer<typeof AssetStateSchema>
import WalTimeline from './WalTimeline'
import OverviewTab from './AssetDetailPanel/OverviewTab'
import GovernanceTab from './AssetDetailPanel/GovernanceTab'
import SizingTab from './AssetDetailPanel/SizingTab'
import DiagnosticsTab from './AssetDetailPanel/DiagnosticsTab'
import Tabs, { TabPanel } from './ui/Tabs'

interface Props {
  asset: AssetState
  name: string
  onClose: () => void
}

type TabId = 'overview' | 'governance' | 'sizing' | 'diagnostics' | 'wal'

const TABS: { id: TabId; label: string; icon: React.ReactNode }[] = [
  { id: 'overview', label: 'Overview', icon: <BarChart3 className="w-3.5 h-3.5" strokeWidth={1.5} /> },
  { id: 'governance', label: 'Governance', icon: <Shield className="w-3.5 h-3.5" strokeWidth={1.5} /> },
  { id: 'sizing', label: 'Sizing', icon: <Sliders className="w-3.5 h-3.5" strokeWidth={1.5} /> },
  { id: 'diagnostics', label: 'Diagnostics', icon: <Activity className="w-3.5 h-3.5" strokeWidth={1.5} /> },
  { id: 'wal', label: 'WAL', icon: <List className="w-3.5 h-3.5" strokeWidth={1.5} /> },
]

/**
 * Slide-over detail panel for a single asset. Contains tabs for Overview, Governance, Sizing, Diagnostics, and WAL timeline.
 */
export default function AssetDetailPanel({ asset, name, onClose }: Props) {
  const [tab, setTab] = useState<TabId>('overview')

  // Determine model freshness from asset metrics
  const nTrades = asset.metrics?.n_trades ?? 0
  const lastSignalDate = asset.metrics?.last_signal_date
  const daysSinceLastSignal = lastSignalDate
    ? Math.round((Date.now() - new Date(lastSignalDate).getTime()) / (1000 * 60 * 60 * 24))
    : null
  const modelAgeDays = daysSinceLastSignal ?? null
  const modelStale = modelAgeDays !== null && modelAgeDays > 90

  return (
    <>
      {/* Overlay backdrop for mobile full-screen panel */}
      <div className="fixed inset-0 z-50 bg-black/40 sm:bg-black/40 sm:hidden"
           onClick={onClose} aria-hidden="true" />
      <div className="fixed inset-0 sm:inset-y-0 sm:right-0 z-50 w-full sm:w-[420px] bg-app sm:border-l border-default shadow-2xl flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-default shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="font-bold text-sm text-primary truncate">{name}</span>
            {asset.sell_only && (
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                asset.tripwire_active
                  ? 'bg-gov-red-muted text-gov-red border-gov-red/20 animate-pulse'
                  : 'bg-gov-yellow-muted text-gov-yellow border-gov-yellow/20'
              }`}>
                {asset.tripwire_active ? 'TRIPWIRE' : 'SELL-ONLY'}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {/* Model freshness indicator (W3) */}
            {modelAgeDays !== null && (
              <span
                className={`flex items-center gap-1 text-[9px] font-mono px-1.5 py-0.5 rounded-full border ${
                  modelStale
                    ? 'bg-gov-red-muted text-gov-red border-gov-red/20'
                    : modelAgeDays > 60
                    ? 'bg-gov-yellow-muted text-gov-yellow border-gov-yellow/20'
                    : 'bg-gov-green-muted text-gov-green border-gov-green/20'
                }`}
                title={`Last signal ${modelAgeDays} days ago${nTrades > 0 ? ` · ${nTrades} trades` : ''} — signal freshness, not retrain age`}
              >
                <Clock className="w-2.5 h-2.5" strokeWidth={2} />
                {modelAgeDays}d
              </span>
            )}
            <button
              type="button"
              onClick={onClose}
              className="min-h-[36px] min-w-[36px] inline-flex items-center justify-center rounded-md hover:bg-panel transition-colors"
              aria-label="Close detail panel"
            >
              <X className="w-4 h-4 text-secondary" strokeWidth={2} />
            </button>
          </div>
        </div>

        {/* Tabs using canonical Tabs component — generic type inferred from TABS */}
        <Tabs tabs={TABS} activeTab={tab} onTabChange={setTab} />

        <TabPanel id="overview" active={tab === 'overview'} className="p-4 space-y-4">
          <OverviewTab asset={asset} />
        </TabPanel>
        <TabPanel id="governance" active={tab === 'governance'} className="p-4 space-y-4">
          <GovernanceTab asset={asset} />
        </TabPanel>
        <TabPanel id="sizing" active={tab === 'sizing'} className="p-4 space-y-4">
          <SizingTab asset={asset} />
        </TabPanel>
        <TabPanel id="diagnostics" active={tab === 'diagnostics'} className="p-4 space-y-4">
          <DiagnosticsTab asset={asset} />
        </TabPanel>
        <TabPanel id="wal" active={tab === 'wal'} className="p-4 space-y-4">
          <WalTimeline assetName={name} />
        </TabPanel>
      </div>
    </>
  )
}
