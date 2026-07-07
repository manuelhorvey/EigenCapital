import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchApi } from '../lib/api'
import { WeeklyReviewSchema } from '../lib/schemas'
import type { WeeklyReview } from '../types/portfolio'

const STORAGE_KEY = 'weekly_review_acknowledged'

/** Fetches the weekly review and provides acknowledge/dismiss controls with localStorage persistence. @returns {{ data: WeeklyReview | null, show: boolean, isPending: boolean, isError: boolean, acknowledge: () => void, dismiss: () => void }} - Review data and interaction helpers */
export function useWeeklyReview() {
  const queryClient = useQueryClient()

  const query = useQuery({
    queryKey: ['weeklyReview'],
    queryFn: async () => {
      const json = await fetchApi<unknown>('/weekly-review.json')
      const parsed = WeeklyReviewSchema.safeParse(json)
      if (!parsed.success) {
        console.error('[WeeklyReview] validation failed:', parsed.error.issues)
        throw new Error('Invalid weekly review data')
      }
      return parsed.data as WeeklyReview
    },
    staleTime: 30_000,
    refetchInterval: 120_000,
  })

  const acknowledge = useMutation({
    mutationFn: () => fetchApi('/weekly-review/acknowledge', { method: 'POST' }),
    onSuccess: () => {
      if (query.data) {
        localStorage.setItem(STORAGE_KEY, query.data.week_label)
      }
      queryClient.invalidateQueries({ queryKey: ['weeklyReview'] })
    },
  })

  const lastAcknowledged = typeof window !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null
  const show = !!query.data && query.data.week_label !== lastAcknowledged

  return {
    data: query.data ?? null,
    show,
    isPending: query.isPending,
    isError: query.isError,
    acknowledge: () => acknowledge.mutate(),
    dismiss: () => {
      if (query.data) {
        localStorage.setItem(STORAGE_KEY, query.data.week_label)
      }
    },
  }
}
