import { useState } from 'react'
import { X, Shield, Sliders, Activity, BarChart3, List } from 'lucide-react'
import type { AssetState } from '../types/portfolio'
import WalTimeline from './WalTimeline'
import OverviewTab from './AssetDetailPanel/OverviewTab'
import GovernanceTab from './AssetDetailPanel/GovernanceTab'
import SizingTab from './AssetDetailPanel/SizingTab'
import DiagnosticsTab from './AssetDetailPanel/DiagnosticsTab'

type TabId = 'overview' | 'governance' | 'sizing' | 'diagnostics' | 'wal'

interface Props {
  asset: AssetState
  name: string
  onClose: () => void
}

const TABS: { id: TabId; label: string; icon: typeof Shield }[] = [
  { id: 'overview', label: 'Overview', icon: BarChart3 },
  { id: 'governance', label: 'Governance', icon: Shield },
  { id: 'sizing', label: 'Sizing', icon: Sliders },
  { id: 'diagnostics', label: 'Diagnostics', icon: Activity },
  { id: 'wal', label: 'WAL', icon: List },
]

/**
 * Slide-over detail panel for a single asset. Contains tabs for Overview, Governance, Sizing, Diagnostics, and WAL timeline.
 * @param {{ asset: AssetState, name: string, onClose: () => void }} props
 */
export default function AssetDetailPanel({ asset, name, onClose }: Props) {
  const [tab, setTab] = useState<TabId>('overview')

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
          <button
            type="button"
            onClick={onClose}
            className="min-h-[36px] min-w-[36px] inline-flex items-center justify-center rounded-md hover:bg-panel transition-colors"
            aria-label="Close detail panel"
          >
            <X className="w-4 h-4 text-secondary" strokeWidth={2} />
          </button>
        </div>

        <div className="flex border-b border-default overflow-x-auto">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
                tab === id
                  ? 'border-accent-emerald text-primary'
                  : 'border-transparent text-tertiary hover:text-secondary'
              }`}
            >
              <Icon className="w-3.5 h-3.5" strokeWidth={1.5} />
              {label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {tab === 'overview' && <OverviewTab asset={asset} />}
          {tab === 'governance' && <GovernanceTab asset={asset} />}
          {tab === 'sizing' && <SizingTab asset={asset} />}
          {tab === 'diagnostics' && <DiagnosticsTab asset={asset} />}
          {tab === 'wal' && <WalTimeline assetName={name} />}
        </div>
      </div>
    </>
  )
}
