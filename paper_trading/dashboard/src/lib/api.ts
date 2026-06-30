import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { UseQueryOptions, UseMutationOptions } from '@tanstack/react-query'
import type { z } from 'zod'
import { authHeaders } from './auth'

export async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const headers = { ...authHeaders(), ...options?.headers } as Record<string, string>
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), 8000)
  const res = await fetch(endpoint, { ...options, headers, signal: controller.signal })
  clearTimeout(timeoutId)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  // Auto-unwrap state metadata envelope if present
  if (json && typeof json === 'object' && 'data' in json && 'state_timestamp' in json) {
    return json.data as T
  }
  return json as T
}

export function createApiQuery<T>(
  endpoint: string,
  schema?: z.ZodType<T>,
  queryKey?: string,
) {
  const tag = queryKey ?? endpoint.replace(/^\//, '').replace(/\.json$/, '')
  const fetchFn = async (): Promise<T> => {
    const json = await fetchApi<unknown>(endpoint)
    if (schema) {
      const parsed = schema.safeParse(json)
      if (!parsed.success) {
        console.error(`[${tag}] validation failed:`, parsed.error.issues)
        throw new Error(`Invalid ${tag} data from server`)
      }
      return parsed.data
    }
    return json as T
  }
  return (queryOptions?: Partial<UseQueryOptions<T>>) =>
    useQuery<T>({
      queryKey: [tag],
      queryFn: fetchFn,
      ...queryOptions,
    })
}

export function createApiMutation<TResponse, TVariables = void>(
  endpoint: string,
  method: 'POST' | 'PUT' | 'DELETE' = 'POST',
  invalidateKeys?: string[][],
) {
  return (mutationOptions?: Partial<UseMutationOptions<TResponse, Error, TVariables>>) =>
    useMutation<TResponse, Error, TVariables>({
      mutationFn: async (variables) => {
        const headers: Record<string, string> = { ...authHeaders() }
        if (variables !== undefined) headers['Content-Type'] = 'application/json'
        const res = await fetch(endpoint, {
          method,
          headers,
          body: variables !== undefined ? JSON.stringify(variables) : undefined,
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json() as Promise<TResponse>
      },
      ...mutationOptions,
    })
}

export async function postApi(endpoint: string): Promise<void> {
  const res = await fetch(endpoint, { method: 'POST', headers: authHeaders() })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
}
