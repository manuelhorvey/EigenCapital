import { Component, type ReactNode, type ErrorInfo } from 'react'
import PanelFallback from './ui/PanelFallback'
import { captureError, sanitise } from '../lib/errorReporting'

interface Props {
  children: ReactNode
  fallback?: ReactNode | ((error: Error) => ReactNode)
  title?: string
}

interface State {
  hasError: boolean
  error: Error | null
}

/** React error boundary with optional fallback UI and Sentry error reporting.
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
    // Report sanitised error to Sentry (or console.error if Sentry not configured).
    // Sanitisation (JWT tokens, API keys, file paths) is handled inside captureError
    // and also applied to the component stack before passing as context.
    captureError(error, { componentStack: sanitise(info.componentStack ?? '') })
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
