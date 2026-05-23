import { useState } from 'react'
import { ChevronRight, Terminal } from 'lucide-react'
import { useEngineLogs } from '../hooks/useEngineLogs'
import Panel from './ui/Panel'
import SectionHeader from './ui/SectionHeader'

function logColor(line: string): string {
  if (line.includes('[ERROR]') || line.includes('[CRITICAL]')) return 'text-gov-red'
  if (line.includes('[WARNING]')) return 'text-gov-yellow'
  if (line.includes('[INFO]')) return 'text-gov-green'
  return 'text-tertiary'
}

export default function EngineLogs() {
  const [open, setOpen] = useState(false)
  const { data, isFetching, error } = useEngineLogs()

  const lineCount = data ? data.split('\n').length : 0

  return (
    <Panel padding="none" className="overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 text-xs font-medium text-secondary hover:bg-panel/50 transition-colors border-b border-default"
      >
        <div className="flex items-center gap-2">
          <Terminal className="w-3.5 h-3.5 text-tertiary" strokeWidth={1.5} />
          <span>Engine Logs</span>
          <span className="px-1.5 py-0.5 rounded text-2xs bg-panel text-tertiary font-mono border border-default/50">
            {lineCount > 0 ? `${lineCount} lines` : '—'}
          </span>
        </div>
        <div className="flex items-center gap-2 text-tertiary">
          {isFetching && (
            <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          )}
          <ChevronRight className={`w-3.5 h-3.5 transition-transform duration-200 ${open ? 'rotate-90' : ''}`} strokeWidth={1.5} />
        </div>
      </button>
      {open && (
        <div className="max-h-72 overflow-y-auto">
          {error ? (
            <div className="px-4 py-6 text-xs text-tertiary text-center font-mono">
              [log unavailable]
            </div>
          ) : data ? (
            <pre className="px-4 py-3 text-[11px] font-mono leading-relaxed whitespace-pre-wrap break-all">
              {data.split('\n').map((line, i) => (
                <span key={i} className={`${logColor(line)} block`}>{line || '\u00A0'}</span>
              ))}
            </pre>
          ) : (
            <div className="px-4 py-6 flex items-center justify-center gap-2">
              <svg className="w-3.5 h-3.5 text-tertiary animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span className="text-xs text-tertiary font-mono">Loading...</span>
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}
