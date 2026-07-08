import * as Sentry from '@sentry/react'

const SENTRY_DSN = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_SENTRY_DSN) || ''

/** Initialise Sentry error reporting. Safe to call even without a DSN — it's a no-op. */
export function initErrorReporting() {
  if (!SENTRY_DSN) {
    if (typeof console !== 'undefined') console.warn('[Sentry] No DSN configured — errors will not be reported')
    return
  }
  Sentry.init({
    dsn: SENTRY_DSN,
    environment: import.meta.env.MODE || 'development',
    // Error monitoring only — no tracing, no session replay, no logs
    tracesSampleRate: 0,
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,
    integrations: [],
    beforeSend(event) {
      if (event.exception?.values) {
        for (const value of event.exception.values) {
          if (value.value) value.value = sanitise(value.value)
        }
      }
      if (event.message) event.message = sanitise(event.message)
      return event
    },
  })
}

/* ── Sanitisation (shared with ErrorBoundary) ──────────────────── */
export function sanitise(msg: string): string {
  return msg
    .replace(/eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+/g, '[JWT]')
    .replace(/(?:api[_-]?key|token|secret|password|auth)[=:][^\s)"'&,;]+/gi, '[REDACTED]')
    .replace(/(\/[a-zA-Z0-9_\-.]{3,})/g, '[PATH]')
}

/** Sanitise an error's message in-place (shared with ErrorBoundary). */
export function sanitiseError(error: Error): Error {
  error.message = sanitise(error.message)
  return error
}

/** Report an error to Sentry (or console.error if Sentry is not configured).
 *  The error message is sanitised before sending. */
export function captureError(error: Error, context?: Record<string, unknown>): void {
  sanitiseError(error)

  if (!SENTRY_DSN) {
    console.error('[ErrorBoundary]', error.name, error.message)
    return
  }

  Sentry.withScope((scope) => {
    if (context) scope.setExtras(context)
    Sentry.captureException(error)
  })
}

/** Add a breadcrumb for non-fatal events (e.g., API failures that recover). */
export function addErrorBreadcrumb(category: string, message: string): void {
  if (!SENTRY_DSN) return
  Sentry.addBreadcrumb({ category, message, level: 'error' })
}
