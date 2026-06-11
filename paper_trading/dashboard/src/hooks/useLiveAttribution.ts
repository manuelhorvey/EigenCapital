import { createApiQuery } from '../lib/api'
import { z } from 'zod'

const LiveAttributionSchema = z.array(
  z.object({
    asset: z.string(),
    side: z.string().nullable(),
    entry_price: z.number().nullable(),
    current_value: z.number().nullable(),
    running_mae: z.number().nullable(),
    running_mfe: z.number().nullable(),
  }),
)

export type LiveAttributionRecord = z.infer<typeof LiveAttributionSchema.element>

export const useLiveAttribution = createApiQuery<z.infer<typeof LiveAttributionSchema>>(
  '/attribution/live.json',
  LiveAttributionSchema,
  { refetchInterval: 60_000, staleTime: 50_000 },
)
