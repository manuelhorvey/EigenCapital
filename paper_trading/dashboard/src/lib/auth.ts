const TOKEN_META_SELECTOR = 'meta[name="api-token"]'
const LS_KEY = "eigencapital_api_token"

function getToken(): string | null {
  const meta = document.querySelector<HTMLMetaElement>(TOKEN_META_SELECTOR)
  if (meta?.content) return meta.content
  const ls = localStorage.getItem(LS_KEY)
  if (ls) return ls
  return null
}

export function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}
