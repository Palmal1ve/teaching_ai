import type { TimelineRow } from '../api/client'

export const LOW_CONFIDENCE = 0.5
const MIN_SPAN_MS = 1000

export function moveBoundary(rows: TimelineRow[], index: number, ms: number): TimelineRow[] {
  const left = rows[index]
  const right = rows[index + 1]
  const clamped = Math.round(
    Math.min(Math.max(ms, left.start_ms + MIN_SPAN_MS), right.end_ms - MIN_SPAN_MS),
  )
  return rows.map((row, i) => {
    if (i === index) return { ...row, end_ms: clamped }
    if (i === index + 1) return { ...row, start_ms: clamped }
    return row
  })
}

export function reassign(rows: TimelineRow[], index: number, slide: number | null): TimelineRow[] {
  return rows.map((row, i) => (i === index ? { ...row, slide } : row))
}

export function split(rows: TimelineRow[], index: number): TimelineRow[] {
  const row = rows[index]
  const middle = Math.round((row.start_ms + row.end_ms) / 2)
  if (middle - row.start_ms < MIN_SPAN_MS) return rows
  return [
    ...rows.slice(0, index),
    { ...row, end_ms: middle },
    { ...row, start_ms: middle },
    ...rows.slice(index + 1),
  ]
}
