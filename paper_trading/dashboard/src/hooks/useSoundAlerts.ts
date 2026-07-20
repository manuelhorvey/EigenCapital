import { useCallback, useState } from 'react'

const STORAGE_KEY = 'ec-sound-alerts'

function isSoundEnabled(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== 'false'
  } catch {
    return true
  }
}

function playBeep() {
  try {
    const ctx = new AudioContext()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.type = 'sine'
    osc.frequency.value = 880
    gain.gain.value = 0.15
    osc.connect(gain).connect(ctx.destination)
    osc.start()
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3)
    osc.stop(ctx.currentTime + 0.3)
    osc.onended = () => ctx.close()
  } catch {
    /* audio not available */
  }
}

export function playAlertSound() {
  if (isSoundEnabled()) playBeep()
}

/** Play a preview beep regardless of the sound-enabled toggle. */
export function playTestSound() {
  playBeep()
}

export function useSoundAlerts() {
  const [enabled, setEnabled] = useState(isSoundEnabled)

  const toggle = useCallback(() => {
    setEnabled(prev => {
      const next = !prev
      try {
        localStorage.setItem(STORAGE_KEY, String(next))
      } catch { /* noop */ }
      return next
    })
  }, [])

  return { enabled, toggle } as const
}
