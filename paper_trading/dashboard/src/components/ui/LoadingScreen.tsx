import { Activity } from 'lucide-react'

interface LoadingScreenProps {
  title?: string
  subtitle?: string
}

export default function LoadingScreen({
  title = 'Connecting to QuantForge Engine',
  subtitle = 'Waiting for paper trading data…',
}: LoadingScreenProps) {
  return (
    <div className="min-h-screen bg-app flex flex-col items-center justify-center gap-5 px-6 animate-fade-in">
      <div className="relative">
        <div className="absolute inset-0 rounded-full bg-accent-emerald/20 blur-xl animate-pulse-subtle" />
        <div className="relative w-12 h-12 rounded-xl panel flex items-center justify-center border-strong">
          <Activity className="w-6 h-6 text-accent-emerald animate-pulse" strokeWidth={1.75} />
        </div>
      </div>
      <div className="text-center max-w-sm">
        <h2 className="text-primary text-lg font-semibold tracking-tight">{title}</h2>
        <p className="text-tertiary text-sm mt-1.5">{subtitle}</p>
      </div>
      <div className="flex gap-1 mt-1">
        {[0, 150, 300].map(delay => (
          <span
            key={delay}
            className="w-1 h-1 rounded-full bg-accent-emerald/50 animate-pulse"
            style={{ animationDelay: `${delay}ms` }}
          />
        ))}
      </div>
    </div>
  )
}
