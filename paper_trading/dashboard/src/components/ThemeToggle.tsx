import { memo } from 'react'
import { Sun, Moon, Monitor } from 'lucide-react'
import { useTheme, type ThemeMode } from '../hooks/useTheme'

const MODE_ICONS: Record<ThemeMode, typeof Sun> = {
  dark: Moon,
  light: Sun,
  system: Monitor,
}

const MODE_LABELS: Record<ThemeMode, string> = {
  dark: 'Dark mode',
  light: 'Light mode',
  system: 'System theme',
}

/**
 * Theme toggle button for the ticker rail.
 * Cycles through: dark → light → system → dark...
 */
function ThemeToggleInner() {
  const { mode, setMode } = useTheme()

  const cycle = () => {
    const next: Record<ThemeMode, ThemeMode> = {
      dark: 'light',
      light: 'system',
      system: 'dark',
    }
    setMode(next[mode])
  }

  const Icon = MODE_ICONS[mode]

  return (
    <button
      type="button"
      onClick={cycle}
      className="min-h-[22px] min-w-[22px] inline-flex items-center justify-center rounded text-tertiary hover:text-primary active:scale-[0.97] focus-ring transition-colors"
      title={MODE_LABELS[mode]}
      aria-label={`Theme: ${MODE_LABELS[mode]}. Click to cycle.`}
    >
      <Icon className="w-3 h-3" strokeWidth={2} />
    </button>
  )
}

const ThemeToggle = memo(ThemeToggleInner)
export default ThemeToggle
