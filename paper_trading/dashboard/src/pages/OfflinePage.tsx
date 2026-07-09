import { useEffect, useRef, useState } from 'react'
import { WifiOff, RefreshCw } from 'lucide-react'
import Button from '../components/ui/Button'

/**
 * Offline page.
 * Shown when the browser detects no network connectivity.
 * Auto-refreshes when connectivity is restored after an offline→online transition.
 */
export default function OfflinePage() {
  const [isOnline, setIsOnline] = useState(navigator.onLine)
  const wasOffline = useRef(!navigator.onLine)

  useEffect(() => {
    const goOnline = () => {
      setIsOnline(true)
      wasOffline.current = true
    }
    const goOffline = () => {
      setIsOnline(false)
    }

    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)

    return () => {
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
    }
  }, [])

  // Auto-reload only on offline→online transition, never on initial mount
  useEffect(() => {
    if (isOnline && wasOffline.current) {
      wasOffline.current = false
      const timer = setTimeout(() => window.location.reload(), 1500)
      return () => clearTimeout(timer)
    }
  }, [isOnline])

  if (isOnline) {
    return (
      <div className="min-h-[60vh] flex flex-col items-center justify-center gap-6 px-6 animate-fade-in">
        <div className="text-center max-w-md">
          <p className="text-sm text-accent-emerald font-semibold">Connection restored — reloading…</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-[60vh] flex flex-col items-center justify-center gap-6 px-6 animate-fade-in">
      <div className="w-16 h-16 rounded-xl panel flex items-center justify-center">
        <WifiOff className="w-8 h-8 text-tertiary/60" strokeWidth={1.25} />
      </div>

      <div className="text-center max-w-md">
        <h1 className="text-lg font-bold text-primary tracking-tight">No connection</h1>
        <p className="text-sm text-tertiary mt-2 leading-relaxed">
          Your browser has lost network connectivity. The dashboard will
          automatically reload when the connection is restored.
        </p>
      </div>

      <Button
        variant="primary"
        onClick={() => window.location.reload()}
        icon={<RefreshCw className="w-3.5 h-3.5" strokeWidth={2} />}
      >
        Try again
      </Button>
    </div>
  )
}
