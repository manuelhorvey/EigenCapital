import Panel from '../components/ui/Panel'
import { EntranceAnimator } from '../components/ui'
import { SECTION_SPACING } from '../design/grid'
import { useWidgetVisibility, type WidgetId, getWidgetLabel } from '../hooks/useWidgetVisibility'
import { useSoundAlerts, playTestSound } from '../hooks/useSoundAlerts'
import { useBrowserNotifications } from '../hooks/useBrowserNotifications'

const ALL_WIDGETS: WidgetId[] = [
  'system-status',
  'system-health',
  'quick-stats',
  'equity-curve',
  'open-positions',
  'positions-list',
  'risk-signals',
  'optimizer',
]

export default function SettingsPage() {
  const { visible, toggle, reset } = useWidgetVisibility()
  const { enabled: soundEnabled, toggle: toggleSound } = useSoundAlerts()
  const { enabled: desktopEnabled, setEnabled: setDesktopEnabled } = useBrowserNotifications()

  return (
    <div className={SECTION_SPACING}>
      <EntranceAnimator variant="fade-up">
        <Panel padding="md">
          <div className="space-y-6">
            <div className="border-t border-default pt-6">
              <h2 className="text-xs font-semibold text-primary uppercase tracking-wider">Dashboard Widgets</h2>
              <p className="text-[10px] text-tertiary mt-1 mb-3">Show or hide sections on the dashboard</p>
              <div className="space-y-2">
                {ALL_WIDGETS.map(id => (
                  <label
                    key={id}
                    className="flex items-center justify-between py-2 px-3 rounded-lg bg-surface/50 border border-default cursor-pointer hover:border-strong transition-colors"
                  >
                    <span className="text-xs text-primary font-medium">{getWidgetLabel(id)}</span>
                    <input
                      type="checkbox"
                      className="toggle"
                      checked={visible[id]}
                      onChange={() => toggle(id)}
                    />
                  </label>
                ))}
              </div>
              <button
                type="button"
                onClick={reset}
                className="mt-3 text-2xs text-tertiary hover:text-secondary transition-colors font-medium"
              >
                Reset to defaults
              </button>
            </div>

            <div className="border-t border-default pt-6">
              <h2 className="text-xs font-semibold text-primary uppercase tracking-wider">Notifications</h2>
              <div className="mt-3 space-y-3">
                <label className="flex items-center justify-between py-2 px-3 rounded-lg bg-surface/50 border border-default" title="Critical alerts will still trigger OS notifications when enabled">
                  <div>
                    <span className="text-xs text-primary font-medium">Desktop Notifications</span>
                    <p className="text-[10px] text-tertiary mt-0.5">OS alerts for critical events — browser will ask for permission</p>
                  </div>
                  <input type="checkbox" className="toggle" checked={desktopEnabled} onChange={e => setDesktopEnabled(e.target.checked)} />
                </label>
                <label className="flex items-center justify-between py-2 px-3 rounded-lg bg-surface/50 border border-default">
                  <div>
                    <span className="text-xs text-primary font-medium">Sound Alerts</span>
                    <p className="text-[10px] text-tertiary mt-0.5">Play sound on critical alerts</p>
                  </div>
                  <input type="checkbox" className="toggle" checked={soundEnabled} onChange={toggleSound} />
                </label>
                {soundEnabled && (
                  <button
                    type="button"
                    onClick={playTestSound}
                    className="ml-3 text-2xs text-tertiary hover:text-secondary transition-colors font-medium"
                  >
                    Test sound
                  </button>
                )}
              </div>
            </div>

            <div className="border-t border-default pt-6">
              <h2 className="text-xs font-semibold text-primary uppercase tracking-wider">About</h2>
              <div className="mt-3 px-3 py-2 rounded-lg bg-surface/50 border border-default space-y-1">
                <div className="flex justify-between text-xs">
                  <span className="text-tertiary">Version</span>
                  <span className="text-primary font-mono">2.0.0</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-tertiary">Engine</span>
                  <span className="text-primary font-mono">EigenCapital</span>
                </div>
              </div>
            </div>
          </div>
        </Panel>
      </EntranceAnimator>
    </div>
  )
}
