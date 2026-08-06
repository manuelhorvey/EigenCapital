import { Component, type ReactNode, type ErrorInfo } from 'react'
import PanelFallback from './ui/PanelFallback'

interface Props {
  children: ReactNode
  fallback?: ReactNode | ((error: Error, retry: () => void) => ReactNode)
  title?: string
  /** Re-mount children when any of these keys change (e.g. route path) */
  resetKey?: string
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
  }

  componentDidUpdate(prevProps: Props) {
    // If the reset key changes (e.g. navigating to a different route), clear the error.
    if (this.props.resetKey !== prevProps.resetKey && this.state.hasError) {
      this.setState({ hasError: false, error: null })
    }
  }

  private retry = () => {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        if (typeof this.props.fallback === 'function') {
          return this.props.fallback(this.state.error!, this.retry)
        }
        return this.props.fallback
      }
      return <PanelFallback title={this.props.title ?? 'Section'} error={this.state.error ?? undefined} onRetry={this.retry} />
    }
    return this.props.children
  }
}
