import { useMutation, useQueryClient } from '@tanstack/react-query'
import { authHeaders } from '../lib/auth'

interface CounterfactualParams {
  decision_id: string
  override_type: 'gate' | 'probability' | 'signal' | 'sltp'
  field?: string
  value?: unknown
}

export function useCounterfactual() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (params: CounterfactualParams) => {
      const res = await fetch('/provenance/counterfactual', {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: 'HTTP ' + res.status }))
        throw new Error(err.error || 'Counterfactual request failed')
      }
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['provenance'] })
    },
  })
}
