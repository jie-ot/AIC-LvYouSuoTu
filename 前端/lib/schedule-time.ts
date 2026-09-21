/** Format itinerary clocks. An earlier end clock means next-day arrival. */

export function parseClockMinutes(value: string): number | null {
  const match = value.match(/^(\d{1,2}):(\d{2})$/u)
  if (!match) return null
  const hours = Number(match[1])
  const minutes = Number(match[2])
  if (hours > 23 || minutes > 59) return null
  return hours * 60 + minutes
}

export function isOvernight(start: string, end: string): boolean {
  const startMinutes = parseClockMinutes(start)
  const endMinutes = parseClockMinutes(end)
  return startMinutes != null && endMinutes != null && endMinutes < startMinutes
}

export function formatScheduleTimeRange(
  startTime?: string | null,
  endTime?: string | null,
  separator = "–",
): string {
  const start = (startTime || "").trim()
  const end = (endTime || "").trim()
  if (start && end) {
    return isOvernight(start, end) ? `${start}${separator}次日${end}` : `${start}${separator}${end}`
  }
  return start
}

export function scheduleSpanMinutes(start: string, end: string): number | null {
  const startMinutes = parseClockMinutes(start)
  const endMinutes = parseClockMinutes(end)
  if (startMinutes == null || endMinutes == null) return null
  const span = endMinutes < startMinutes ? endMinutes + 24 * 60 - startMinutes : endMinutes - startMinutes
  return span > 0 ? span : null
}
