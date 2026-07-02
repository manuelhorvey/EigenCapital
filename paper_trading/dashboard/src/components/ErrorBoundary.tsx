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

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
    // Report to backend
    try {
      const body = JSON.stringify({ error: error.message, stack: info.componentStack, name: error.name })
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
