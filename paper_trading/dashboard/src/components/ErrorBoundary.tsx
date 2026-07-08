import { Component, type ReactNode, type ErrorInfo } from 'react'
import PanelFallback from './ui/PanelFallback'

interface Props {
  children: ReactNode
  fallback?: ReactNode | ((error: Error) => ReactNode)
  title?: string
}

interface State {
  hasError: boolean
  error: Error | null
}

/** React error boundary with optional fallback UI and server-side error logging.
 * @param {ReactNode} props.children - Child components to wrap
 * @param {ReactNode|Function} [props.fallback] - Custom fallback UI or error-to-node function
 * @param {string} [props.title] - Section title for default fallback */
export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Log a sanitised error message — strip sensitive-looking substrings
    // (e.g. tokens, passwords, file paths) before logging or reporting.
    const sanitised = (msg: string) =>
      msg.replace(/eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+/g, '[JWT]')
         .replace(/(?:api[_-]?key|token|secret|password|auth)[=:][^\s)"'&,;]+/gi, '[REDACTED]')
         .replace(/(\/[a-zA-Z0-9_\-.]+){3,}/g, '[PATH]')

    const safeMessage = sanitised(error.message)
    const safeStack = sanitised(info.componentStack ?? '')
    console.error('[ErrorBoundary]', error.name, safeMessage)

    // Report sanitised payload to backend
    try {
      const body = JSON.stringify({ error: safeMessage, stack: safeStack, name: error.name })
      fetch('/api/log-error', { method: 'POST', body, headers: { 'Content-Type': 'application/json' } }).catch(() => {})
    } catch {
      // swallow
    }
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        if (typeof this.props.fallback === 'function') {
          return this.props.fallback(this.state.error!)
        }
        return this.props.fallback
      }
      return <PanelFallback title={this.props.title ?? 'Section'} error={this.state.error ?? undefined} />
    }
    return this.props.children
  }
}
