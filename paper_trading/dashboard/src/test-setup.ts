import '@testing-library/jest-dom'
import { beforeEach } from 'vitest'

// ── EventSource polyfill ─────────────────────────────────────────
// JSDOM does not implement EventSource; provide a minimal mock so
// the SSE hook (useSystemSnapshot) does not crash in tests.
class MockEventSource {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 2
  readyState: number = MockEventSource.CONNECTING
  onopen: ((ev: Event) => void) | null = null
  onmessage: ((ev: MessageEvent) => void) | null = null
  onerror: ((ev: Event) => void) | null = null
  url: string
  withCredentials: boolean = false
  private _closed = false

  constructor(url: string | URL) {
    this.url = String(url)
    queueMicrotask(() => {
      if (!this._closed) {
        this.readyState = MockEventSource.OPEN
        this.onopen?.(new Event('open'))
      }
    })
  }

  close() {
    this._closed = true
    this.readyState = MockEventSource.CLOSED
  }

  addEventListener() {}
  removeEventListener() {}
  dispatchEvent(): boolean { return true }
}

globalThis.EventSource = MockEventSource as unknown as typeof EventSource

// ── Clean localStorage between tests ─────────────────────────────
beforeEach(() => {
  localStorage.clear()
})
