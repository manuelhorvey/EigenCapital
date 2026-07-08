import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useLiveAttribution } from '../useLiveAttribution'

vi.mock('../useLiveAttribution', () => ({
  useLiveAttribution: vi.fn(),
}))

describe('useLiveAttribution', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('handles empty response from server', () => {
    vi.mocked(useLiveAttribution).mockReturnValue({
      data: [],
      isPending: false,
      isError: false,
      isSuccess: true,
    } as never)

    const { result } = renderHook(() => useLiveAttribution())
    expect(result.current.isSuccess).toBe(true)
    expect(result.current.data).toEqual([])
  })

  it('returns live attribution records on successful fetch', () => {
    const mockData = [
      { asset: 'EURUSD', side: 'buy', entry_price: 1.1050, current_value: 100_000, running_mae: 0.15, running_mfe: 0.42 },
      { asset: 'GBPUSD', side: 'sell', entry_price: 1.2650, current_value: 100_000, running_mae: 0.08, running_mfe: 0.31 },
    ]
    vi.mocked(useLiveAttribution).mockReturnValue({
      data: mockData,
      isPending: false,
      isError: false,
      isSuccess: true,
    } as never)

    const { result } = renderHook(() => useLiveAttribution())
    expect(result.current.isSuccess).toBe(true)
    expect(result.current.data).toHaveLength(2)
    expect(result.current.data![0].asset).toBe('EURUSD')
  })
})
