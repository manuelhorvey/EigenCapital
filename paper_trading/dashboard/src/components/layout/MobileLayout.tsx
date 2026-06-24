import { useState, useCallback } from 'react'
import {
  Activity, Shield, Zap, BarChart3, TrendingUp, ChevronDown, AlertTriangle, Heart,
  type LucideIcon,
} from 'lucide-react'
import { useSystemSnapshot } from '../../hooks/useSystemSnapshot'
import { useMonitorAlerts } from '../../hooks/useMonitorAlerts'
import StateIndicatorDot from '../ui/StateIndicatorDot'
import ProgressBar from '../ui/ProgressBar'
import { scoreToState } from '../ui/governance'

function AccordionSection({
  title, icon: Icon, defaultOpen, children, scrollable,
}: {
  title: string
  icon?: LucideIcon
  defaultOpen?: boolean
  children: React.ReactNode
  scrollable?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen ?? false)
  return (
    <div className="border border-default rounded-lg overflow-hidden transition-all duration-200 hover:border-strong">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="w-full flex items-center justify-between px-3 py-2.5 bg-panel text-xs font-semibold text-primary"
      >
        <span className="flex items-center gap-2">
          {Icon && <Icon className="w-3.5 h-3.5 text-tertiary" strokeWidth={1.5} />}
          {title}
        </span>
        <ChevronDown
          className={`w-3.5 h-3.5 text-tertiary transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
          strokeWidth={2}
        />
      </button>
      {open && (
        <div className={`bg-app border-t border-default ${scrollable ? 'max-h-64 overflow-y-auto' : ''}`}>
          <div className="px-3 py-2">{children}</div>
        </div>
      )}
    </div>
  )
}

function scrollToSection(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
}

export default function MobileLayout() {
  const { data: bundle } = useSystemSnapshot()
  const state = bundle?.snapshot
  const health = bundle?.live?.health
  const alerts = useMonitorAlerts()
  const portfolio = state?.portfolio

  const healthScores = health?.assets
    ? Object.entries(health.assets).map(([name, h]) => ({ name, score: h.health_score }))
    : []

  const quickActions = [
    { label: 'Trades', icon: Activity, color: 'text-accent-blue', section: 'trades' },
    { label: 'Signals', icon: Zap, color: 'text-accent-purple', section: 'signals' },
    { label: 'Risk', icon: Shield, color: 'text-accent-emerald', section: 'risk' },
    { label: 'Execution', icon: BarChart3, color: 'text-gov-yellow', section: 'execution' },
  ]

  return (
    <div className="flex-1 overflow-y-auto pb-8">
      {/* Carousel: Key Metrics */}
      <div className="overflow-x-auto px-4 py-3">
        <div className="flex gap-3 snap-x snap-mandatory">
          <div className="snap-start shrink-0 w-[160px] bg-panel border border-default rounded-xl p-3 shadow-panel transition-all duration-200 hover:border-strong hover:shadow-card">
            <p className="text-2xs text-tertiary font-medium uppercase tracking-wider">Net Value</p>
            <p className="text-sm font-bold font-mono text-primary tabular-nums mt-1">
              {portfolio?.total_value != null
                ? `$${portfolio.total_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                : '—'}
            </p>
            {portfolio?.total_return != null && (
              <p className={`text-xs font-semibold font-mono tabular-nums mt-0.5 ${portfolio.total_return >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
                {portfolio.total_return >= 0 ? '+' : ''}{portfolio.total_return.toFixed(2)}%
              </p>
            )}
          </div>

          <div className="snap-start shrink-0 w-[160px] bg-panel border border-default rounded-xl p-3 shadow-panel transition-all duration-200 hover:border-strong hover:shadow-card">
            <p className="text-2xs text-tertiary font-medium uppercase tracking-wider">Open Trades</p>
            <p className="text-sm font-bold font-mono text-primary tabular-nums mt-1">
              {portfolio?.open_positions ?? 0}
            </p>
            <p className="text-xs text-tertiary mt-0.5">
              {portfolio?.closed_trades ?? 0} closed
            </p>
          </div>

          <div className="snap-start shrink-0 w-[160px] bg-panel border border-default rounded-xl p-3 shadow-panel transition-all duration-200 hover:border-strong hover:shadow-card">
            <p className="text-2xs text-tertiary font-medium uppercase tracking-wider">Runtime</p>
            <p className="text-sm font-bold font-mono text-primary tabular-nums mt-1">
              {portfolio?.runtime_hours != null ? `${portfolio.runtime_hours.toFixed(0)}h` : '—'}
            </p>
            <p className="text-xs text-tertiary mt-0.5">
              {portfolio?.days_running ?? 0} days
            </p>
          </div>

          {healthScores.slice(0, 3).map(h => (
            <div key={h.name} className="snap-start shrink-0 w-[160px] bg-panel border border-default rounded-xl p-3 shadow-panel transition-all duration-200 hover:border-strong hover:shadow-card">
              <p className="text-2xs text-tertiary font-medium uppercase tracking-wider">{h.name}</p>
              <div className="flex items-center gap-2 mt-1">
                <StateIndicatorDot state={scoreToState(h.score)} size="md" />
                <p className="text-sm font-bold font-mono tabular-nums text-primary">
                  {(h.score * 100).toFixed(0)}%
                </p>
              </div>
              <p className={`text-xs font-semibold mt-0.5 ${h.score >= 0.8 ? 'text-gov-green' : h.score >= 0.5 ? 'text-gov-yellow' : 'text-gov-red'}`}>
                {h.score >= 0.8 ? 'Healthy' : h.score >= 0.5 ? 'Degraded' : 'Critical'}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-4 gap-2 px-4 mb-4">
        {quickActions.map(action => (
          <button
            type="button"
            key={action.label}
            aria-label={action.label}
            onClick={() => scrollToSection(action.section)}
            className="flex flex-col items-center gap-1.5 py-2.5 rounded-lg border border-default bg-panel hover:border-strong hover:shadow-card transition-all duration-200 active:scale-[0.97] focus-ring"
          >
            <action.icon className={`w-4 h-4 ${action.color}`} strokeWidth={1.5} />
            <span className="text-2xs font-medium text-tertiary">{action.label}</span>
          </button>
        ))}
      </div>

      {/* Accordion Sections */}
      <div className="px-4 space-y-2">
        {/* Active Positions */}
        <AccordionSection
          title={`Assets (${healthScores.length})`}
          icon={TrendingUp}
          defaultOpen
          scrollable
        >
          {healthScores.length === 0 ? (
            <p className="text-xs text-tertiary text-center py-4">No data</p>
          ) : (
            <div className="space-y-2">
              {healthScores.map(h => (
                <div key={h.name} className="flex items-center justify-between py-1">
                  <div className="flex items-center gap-2 min-w-0">
                    <StateIndicatorDot state={scoreToState(h.score)} size="sm" />
                    <span className="text-xs font-medium text-primary font-mono truncate">{h.name}</span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <div className="w-16">
                      <ProgressBar value={h.score * 100} height="h-1" />
                    </div>
                    <span className="text-xs font-mono font-bold tabular-nums text-secondary">
                      {(h.score * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </AccordionSection>

        {/* Alerts */}
        <AccordionSection title={`Alerts (${alerts.length})`} icon={AlertTriangle}>
          {alerts.length === 0 ? (
            <div className="flex items-center gap-2 py-2 text-xs text-tertiary">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 text-tertiary" strokeWidth={2} />
              <span>No active alerts</span>
            </div>
          ) : (
            <div className="space-y-1.5">
              {alerts.slice(0, 10).map(alert => (
                <div key={alert.id} className="flex items-start gap-2 py-1.5 text-xs">
                  <AlertTriangle className={`w-3 h-3 mt-0.5 shrink-0 ${
                    alert.severity === 'critical' ? 'text-gov-red'
                    : alert.severity === 'warning' ? 'text-gov-yellow'
                    : 'text-gov-init'
                  }`} strokeWidth={2} />
                  <div className="min-w-0">
                    <p className="text-primary truncate">{alert.message}</p>
                    <p className="text-2xs text-tertiary">{alert.asset}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </AccordionSection>

        {/* Trading Summary */}
        <AccordionSection title="Trading Summary" icon={Activity}>
          <div className="space-y-2 py-1">
            <div className="flex items-center justify-between text-xs">
              <span className="text-tertiary">Closed trades</span>
              <span className="text-primary font-mono">{portfolio?.closed_trades ?? 0}</span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-tertiary">Open positions</span>
              <span className="text-primary font-mono">{portfolio?.open_positions ?? 0}</span>
            </div>
            {portfolio?.total_return != null && (
              <div className="flex items-center justify-between text-xs">
                <span className="text-tertiary">Total return</span>
                <span className={`font-mono ${portfolio.total_return >= 0 ? 'text-gov-green' : 'text-gov-red'}`}>
                  {portfolio.total_return.toFixed(2)}%
                </span>
              </div>
            )}
          </div>
        </AccordionSection>

        {/* System Health */}
        {health?.system_health && (
          <AccordionSection title="System Health" icon={Heart}>
            <div className="grid grid-cols-3 gap-2 py-1">
              <div className="text-center">
                <p className="text-sm font-bold text-gov-green">{health.system_health.n_healthy}</p>
                <p className="text-2xs text-tertiary">Healthy</p>
              </div>
              <div className="text-center">
                <p className="text-sm font-bold text-gov-yellow">{health.system_health.n_degraded}</p>
                <p className="text-2xs text-tertiary">Degraded</p>
              </div>
              <div className="text-center">
                <p className="text-sm font-bold text-gov-red">{health.system_health.n_critical}</p>
                <p className="text-2xs text-tertiary">Critical</p>
              </div>
            </div>
          </AccordionSection>
        )}
      </div>
    </div>
  )
}
