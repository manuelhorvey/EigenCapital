import { useState, useCallback } from 'react'
import { Save, Trash2, Check, FileText } from 'lucide-react'
import Panel from '../components/ui/Panel'
import { EntranceAnimator } from '../components/ui'
import { SECTION_SPACING } from '../design/grid'
import { useWidgetVisibility, type WidgetId, getWidgetLabel } from '../hooks/useWidgetVisibility'
import { useSavedLayouts } from '../hooks/useSavedLayouts'
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
  const { presets, saveLayout, loadLayout, deleteLayout, renameLayout } = useSavedLayouts()

  // Layout management state
  const [layoutName, setLayoutName] = useState('')
  const [saving, setSaving] = useState(false)
  const [savedFeedback, setSavedFeedback] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')

  const handleSaveLayout = useCallback(() => {
    const name = layoutName.trim()
    if (!name) return
    setSaving(true)
    saveLayout(name, 'dashboard', visible)
    setLayoutName('')
    setSavedFeedback(name)
    setTimeout(() => setSavedFeedback(null), 2000)
    setSaving(false)
  }, [layoutName, visible, saveLayout])

  const handleApplyLayout = useCallback((id: string) => {
    const preset = loadLayout(id)
    if (preset) {
      // Apply each widget visibility from the preset
      for (const [widgetId, isVisible] of Object.entries(preset.state)) {
        // Toggle widgets that don't match the preset
        if (visible[widgetId as WidgetId] !== isVisible) {
          toggle(widgetId as WidgetId)
        }
      }
    }
  }, [loadLayout, visible, toggle])

  const handleDeleteLayout = useCallback((id: string) => {
    deleteLayout(id)
  }, [deleteLayout])

  const startRename = useCallback((id: string, currentName: string) => {
    setRenamingId(id)
    setRenameValue(currentName)
  }, [])

  const confirmRename = useCallback((id: string) => {
    const name = renameValue.trim()
    if (name) renameLayout(id, name)
    setRenamingId(null)
  }, [renameValue, renameLayout])

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
                      name={`widget-${id}`}
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
                  <input type="checkbox" name="desktop-notifications" className="toggle" checked={desktopEnabled} onChange={e => setDesktopEnabled(e.target.checked)} />
                </label>
                <label className="flex items-center justify-between py-2 px-3 rounded-lg bg-surface/50 border border-default">
                  <div>
                    <span className="text-xs text-primary font-medium">Sound Alerts</span>
                    <p className="text-[10px] text-tertiary mt-0.5">Play sound on critical alerts</p>
                  </div>
                  <input type="checkbox" name="sound-alerts" className="toggle" checked={soundEnabled} onChange={toggleSound} />
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

            {/* Saved Layouts Management */}
            <div className="border-t border-default pt-6">
              <h2 className="text-xs font-semibold text-primary uppercase tracking-wider">Saved Layouts</h2>
              <p className="text-[10px] text-tertiary mt-1 mb-3">Save and manage dashboard widget layouts</p>

              {/* Save current layout */}
              <div className="flex items-center gap-2 mb-3">
                <input
                  type="text"
                  name="layout-name"
                  aria-label="Layout name"
                  value={layoutName}
                  onChange={e => setLayoutName(e.target.value)}
                  placeholder="Layout name…"
                  className="flex-1 px-2.5 py-1.5 rounded-md bg-surface border border-default text-xs text-primary placeholder:text-muted outline-none focus:border-strong transition-colors"
                  onKeyDown={e => { if (e.key === 'Enter') handleSaveLayout() }}
                />
                <button
                  onClick={handleSaveLayout}
                  disabled={!layoutName.trim() || saving}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs font-medium bg-panel border border-default hover:border-strong disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <Save className="w-3 h-3" strokeWidth={1.5} />
                  Save
                </button>
              </div>

              {savedFeedback && (
                <div className="flex items-center gap-1.5 mb-3 px-2 py-1.5 rounded-md bg-signal-long-muted text-[10px] text-signal-long font-medium animate-fade-in">
                  <Check className="w-3 h-3" strokeWidth={2} />
                  Saved layout "{savedFeedback}"
                </div>
              )}

              {/* Layout presets list */}
              {presets.length === 0 ? (
                <p className="text-[10px] text-tertiary italic">No saved layouts yet</p>
              ) : (
                <div className="space-y-1.5">
                  {presets.map(p => (
                    <div
                      key={p.id}
                      className="flex items-center justify-between py-1.5 px-3 rounded-lg bg-surface/50 border border-default hover:border-strong transition-colors group"
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <FileText className="w-3.5 h-3.5 text-tertiary shrink-0" strokeWidth={1.5} />
                        {renamingId === p.id ? (
                          <input
                            type="text"
                            name="rename-layout"
                            aria-label="Rename layout"
                            value={renameValue}
                            onChange={e => setRenameValue(e.target.value)}
                            className="text-xs font-medium text-primary bg-surface border border-default rounded px-1.5 py-0.5 outline-none w-32"
                            autoFocus
                            onKeyDown={e => {
                              if (e.key === 'Enter') confirmRename(p.id)
                              if (e.key === 'Escape') setRenamingId(null)
                            }}
                            onBlur={() => confirmRename(p.id)}
                          />
                        ) : (
                          <span className="text-xs font-medium text-primary truncate">{p.name}</span>
                        )}
                        <span className="text-[10px] text-tertiary font-mono">
                          {new Date(p.updatedAt).toLocaleDateString()}
                        </span>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          onClick={() => handleApplyLayout(p.id)}
                          className="p-1 rounded hover:bg-surface text-tertiary hover:text-accent-emerald transition-colors"
                          title="Apply this layout"
                        >
                          <Check className="w-3 h-3" strokeWidth={1.5} />
                        </button>
                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          {renamingId !== p.id && (
                            <button
                              onClick={() => startRename(p.id, p.name)}
                              className="p-1 rounded hover:bg-surface text-tertiary hover:text-secondary transition-colors"
                              title="Rename"
                            >
                              <span className="text-[10px] font-medium">✎</span>
                            </button>
                          )}
                          <button
                            onClick={() => handleDeleteLayout(p.id)}
                            className="p-1 rounded hover:bg-surface text-tertiary hover:text-signal-short transition-colors"
                            title="Delete"
                          >
                            <Trash2 className="w-3 h-3" strokeWidth={1.5} />
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
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
