import { BarChart3 } from 'lucide-react'
import ChartDataTable from '../ui/ChartDataTable'

interface FeatureItem {
  feature?: string | null
  importance?: number | null
  error?: string | null
  type?: string | null
}

export default function FeatureImportanceChart({ features }: { features: FeatureItem[] }) {
  if (features.length === 0 || features[0]?.error != null) {
    return (
      <div className="bg-panel rounded-lg border border-default p-4">
        <h3 className="text-xs font-semibold text-secondary mb-3 flex items-center gap-1.5">
          <BarChart3 className="w-3.5 h-3.5" strokeWidth={1.5} />
          Feature Importance
        </h3>
        <div className="text-xs text-tertiary">No feature importance available</div>
      </div>
    )
  }

  return (
    <div className="bg-panel rounded-lg border border-default p-4">
      <h3 className="text-xs font-semibold text-secondary mb-3 flex items-center gap-1.5">
        <BarChart3 className="w-3.5 h-3.5" strokeWidth={1.5} />
        Feature Importance
      </h3>
      <ChartDataTable
        title="Feature Importance"
        columns={[
          { key: 'feature', label: 'Feature' },
          { key: 'importance', label: 'Importance (%)', format: v => `${(Number(v) * 100).toFixed(1)}%` },
          { key: 'type', label: 'Type' },
        ]}
        data={features.slice(0, 15) as unknown as Record<string, unknown>[]}
        summary={`Feature importance for top ${Math.min(features.length, 15)} features`}
      />
      <div className="space-y-1">
        {features.slice(0, 15).map((f, i) => {
          const imp = f.importance ?? 0
          return (
            <div key={f.feature ?? i} className="flex items-center gap-2">
              <span className="text-xs text-tertiary w-2/3 truncate font-mono" title={f.feature ?? ''}>{f.feature ?? '—'}</span>
              <div className="flex-1 h-2 bg-surface rounded-full overflow-hidden">
                <div className="h-full rounded-full bg-accent-emerald" style={{ width: `${(imp * 100).toFixed(1)}%` }} />
              </div>
              <span className="text-2xs text-tertiary font-mono w-10 text-right">{(imp * 100).toFixed(1)}%</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}