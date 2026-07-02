const FLAG_KEY = 'ec_feature_flags'

interface FeatureFlags {
  ENABLE_MAE_MFE_SCATTER?: boolean
}

let _flags: FeatureFlags | null = null

function load(): FeatureFlags {
  try {
    const raw = localStorage.getItem(FLAG_KEY)
    if (raw) return JSON.parse(raw) as FeatureFlags
  } catch {}
  return {}
}

export function getFlag(name: keyof FeatureFlags): boolean {
  if (_flags === null) _flags = load()
  return _flags[name] ?? false
}

export function setFlag(name: keyof FeatureFlags, value: boolean): void {
  if (_flags === null) _flags = load()
  _flags[name] = value
  localStorage.setItem(FLAG_KEY, JSON.stringify(_flags))
}
