import Badge from '../ui/Badge'

interface LayerStatus {
  name: string
  status: 'healthy' | 'warning' | 'critical' | 'unknown'
  detail: string
  metric?: string
}

interface GovernanceStatusGridProps {
  layers: LayerStatus[]
}

export default function GovernanceStatusGrid({ layers }: GovernanceStatusGridProps) {
  if (layers.length === 0) {
    return (
      <div className="bg-panel border border-default rounded-lg p-4 text-center text-xs text-tertiary">
        No governance data available
      </div>
    )
  }

  return (
    <div className="bg-panel border border-default rounded-lg p-3" role="region" aria-label="Governance layer status grid">
      <p className="text-2xs font-semibold text-tertiary uppercase tracking-wider mb-2.5 px-1">
        Governance Layer Status
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2" role="list">
        {layers.map(layer => {
          const badgeVariant = layer.status === 'healthy' ? 'success'
            : layer.status === 'warning' ? 'warning'
            : layer.status === 'critical' ? 'error'
            : 'neutral'

          return (
            <div key={layer.name} className="border border-default rounded-lg px-2.5 py-2 bg-surface/30" role="listitem">
              <div className="flex items-center justify-between gap-1 mb-1">
                <span className="text-2xs font-semibold text-primary">{layer.name}</span>
                <Badge variant={badgeVariant} size="sm" dot>
                  {layer.status === 'healthy' ? 'OK'
                    : layer.status === 'warning' ? 'WARN'
                    : layer.status === 'critical' ? 'CRIT'
                    : 'N/A'}
                </Badge>
              </div>
              <p className="text-2xs text-tertiary truncate" title={layer.detail}>
                {layer.detail}
              </p>
              {layer.metric && (
                <p className="text-[10px] font-mono text-secondary tabular-nums mt-0.5">
                  {layer.metric}
                </p>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
