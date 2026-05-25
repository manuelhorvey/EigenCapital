import { useState, useEffect } from 'react'
import { format } from 'date-fns'

const ET = 'America/New_York'

function toZonedTime(date: Date, tz: string): Date {
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone: tz,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  })
  const parts = formatter.formatToParts(date)
  const get = (type: string) => parseInt(parts.find(p => p.type === type)!.value, 10)
  return new Date(get('year'), get('month') - 1, get('day'), get('hour'), get('minute'), get('second'))
}

interface SessionInfo {
  timeStr: string
  dateStr: string
  day: number
  hour: number
  minute: number
  marketsOpen: boolean
}

export function isMarketOpen(day: number, hour: number): boolean {
  if (day === 6) return false                     // Saturday
  if (day === 0) return hour >= 17                // Sunday open at 5pm ET
  if (day === 5) return hour < 17                 // Friday close at 5pm ET
  return true                                     // Mon-Thu
}

export function useSessionClock(): SessionInfo {
  const [clock, setClock] = useState<SessionInfo>(() => {
    const now = new Date()
    const zoned = toZonedTime(now, ET)
    return {
      timeStr: format(zoned, 'HH:mm:ss'),
      dateStr: format(zoned, 'MMM dd, yyyy'),
      day: zoned.getDay(),
      hour: zoned.getHours(),
      minute: zoned.getMinutes(),
      marketsOpen: isMarketOpen(zoned.getDay(), zoned.getHours()),
    }
  })

  useEffect(() => {
    const id = setInterval(() => {
      const now = new Date()
      const zoned = toZonedTime(now, ET)
      setClock({
        timeStr: format(zoned, 'HH:mm:ss'),
        dateStr: format(zoned, 'MMM dd, yyyy'),
        day: zoned.getDay(),
        hour: zoned.getHours(),
        minute: zoned.getMinutes(),
        marketsOpen: isMarketOpen(zoned.getDay(), zoned.getHours()),
      })
    }, 1000)
    return () => clearInterval(id)
  }, [])

  return clock
}
