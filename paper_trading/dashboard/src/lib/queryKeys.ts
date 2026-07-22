export const QUERY_KEYS = {
  system: ['systemSnapshot'] as const,
  attribution: ['attributionBundle'] as const,
  equity: ['equityHistory'] as const,
  engine: ['engineHealth'] as const,
  provenance: ['provenance'] as const,
  provenanceStats: ['provenanceStats'] as const,
} as const

export type QueryKeyDomain = keyof typeof QUERY_KEYS
