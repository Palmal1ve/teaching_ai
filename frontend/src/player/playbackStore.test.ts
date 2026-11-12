import { beforeEach, describe, expect, it } from 'vitest'

import type { Interval, Segment } from '../api/client'
import { lastStartingBefore, nextIntervalShowing, usePlayback } from './playbackStore'

const segment = (seq: number, start_ms: number): Segment => ({
  id: seq,
  seq,
  start_ms,
  end_ms: start_ms + 1000,
  text: '',
})
const interval = (start_ms: number, end_ms: number, slide: number | null): Interval => ({
  start_ms,
  end_ms,
  slide,
  estimated: false,
})

const lines = [segment(0, 0), segment(1, 5000), segment(2, 9000)]
const timeline = [interval(0, 6000, 1), interval(6000, 8000, null), interval(8000, 20000, 2)]

describe('lastStartingBefore', () => {
  it('finds the row at or before a time', () => {
    expect(lastStartingBefore(lines, 0)).toBe(0)
    expect(lastStartingBefore(lines, 4999)).toBe(0)
    expect(lastStartingBefore(lines, 5000)).toBe(1)
    expect(lastStartingBefore(lines, 99999)).toBe(2)
  })
  it('returns -1 before the first row and for an empty list', () => {
    expect(lastStartingBefore([{ start_ms: 100 }], 0)).toBe(-1)
    expect(lastStartingBefore([], 0)).toBe(-1)
  })
})

describe('playback', () => {
  beforeEach(() => usePlayback.getState().load(lines, timeline))

  it('rewinding moves the line and slide back with no other input', () => {
    const state = usePlayback.getState()
    state.tick(10000)
    expect(usePlayback.getState().activeInterval).toBe(2)
    state.tick(1000)
    expect(usePlayback.getState().activeLine).toBe(0)
    expect(usePlayback.getState().activeInterval).toBe(0)
  })

  it('flipping slides pauses following until a seek', () => {
    const state = usePlayback.getState()
    state.flip(5)
    state.tick(10000)
    expect(usePlayback.getState().flippedTo).toBe(5)
    state.seek(2000)
    expect(usePlayback.getState().flippedTo).toBeNull()
  })

  it('leaves the active indexes untouched between line changes', () => {
    const state = usePlayback.getState()
    state.tick(1000)
    let changes = 0
    const stop = usePlayback.subscribe((now, before) => {
      if (now.activeLine !== before.activeLine) changes += 1
    })
    state.tick(1250)
    state.tick(1500)
    stop()
    expect(changes).toBe(0)
  })
})

describe('nextIntervalShowing', () => {
  const repeated = [interval(0, 10, 1), interval(10, 20, 2), interval(20, 30, 1)]
  it('finds the next time a slide is shown, wrapping to the first', () => {
    expect(nextIntervalShowing(repeated, 1, 5)?.start_ms).toBe(20)
    expect(nextIntervalShowing(repeated, 1, 25)?.start_ms).toBe(0)
    expect(nextIntervalShowing(repeated, 9, 0)).toBeNull()
  })
})
