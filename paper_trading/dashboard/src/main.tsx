import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { initErrorReporting } from './lib/errorReporting'
import ErrorBoundary from './components/ErrorBoundary'
import App from './App'
import './index.css'

// Initialise Sentry error reporting (safe no-op if VITE_SENTRY_DSN is not set)
initErrorReporting()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      staleTime: 20_000,
      refetchOnWindowFocus: true,
      gcTime: 300_000,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </QueryClientProvider>
  </React.StrictMode>,
)
