import { describe, expect, it } from 'vitest'

import type { TimelineRow } from '../api/client'
import { moveBoundary, reassign, split } from './timelineEdits'

const row = (start_ms: number, end_ms: number, slide: number | null): TimelineRow => ({
  start_ms,
  end_ms,
  slide,
  confidence: 0.9,
  method: 'visual',
  source: 'auto',
})
const rows = [row(0, 10000, 1), row(10000, 20000, 2)]

describe('filmstrip edits keep the timeline gap-free', () => {
  it('moves a shared boundary', () => {
    const moved = moveBoundary(rows, 0, 4000)
    expect(moved[0].end_ms).toBe(4000)
    expect(moved[1].start_ms).toBe(4000)
  })
  it('never lets a span collapse', () => {
    expect(moveBoundary(rows, 0, -500)[0].end_ms).toBe(1000)
    expect(moveBoundary(rows, 0, 99999)[1].start_ms).toBe(19000)
  })
  it('reassigns one span, including to no slide', () => {
    expect(reassign(rows, 1, null)[1].slide).toBeNull()
    expect(reassign(rows, 1, null)[0].slide).toBe(1)
  })
  it('splits a span in two', () => {
    const parts = split(rows, 0)
    expect(parts.map((r) => [r.start_ms, r.end_ms])).toEqual([
      [0, 5000],
      [5000, 10000],
      [10000, 20000],
    ])
  })
})
