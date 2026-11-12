import { create } from 'zustand'

import type { Interval, Segment } from '../api/client'

/** Index of the last row starting at or before `ms`, or -1 when `ms` is before them all. */
export function lastStartingBefore(rows: { start_ms: number }[], ms: number): number {
  let low = 0
  let high = rows.length - 1
  let found = -1
  while (low <= high) {
    const middle = (low + high) >> 1
    if (rows[middle].start_ms <= ms) {
      found = middle
      low = middle + 1
    } else {
      high = middle - 1
    }
  }
  return found
}

type Playback = {
  video: HTMLVideoElement | null
  transcript: Segment[]
  timeline: Interval[]
  currentMs: number
  activeLine: number
  activeInterval: number
  flippedTo: number | null
  load: (transcript: Segment[], timeline: Interval[]) => void
  attach: (video: HTMLVideoElement | null) => void
  tick: (ms: number) => void
  seek: (ms: number) => void
  flip: (slide: number) => void
  backToVideo: () => void
}

/**
 * The video's current time is the only source of truth. Everything else is derived here, so
 * rewinding needs no server call and cannot drift. Components subscribe to the active indexes
 * and re-render only when the line or slide changes.
 */
export const usePlayback = create<Playback>((set, get) => ({
  video: null,
  transcript: [],
  timeline: [],
  currentMs: 0,
  activeLine: -1,
  activeInterval: -1,
  flippedTo: null,
  load: (transcript, timeline) =>
    set({ transcript, timeline, currentMs: 0, activeLine: -1, activeInterval: -1, flippedTo: null }),
  attach: (video) => set({ video }),
  tick: (ms) => {
    const { transcript, timeline, activeLine, activeInterval } = get()
    const line = lastStartingBefore(transcript, ms)
    const interval = lastStartingBefore(timeline, ms)
    set(
      line === activeLine && interval === activeInterval
        ? { currentMs: ms }
        : { currentMs: ms, activeLine: line, activeInterval: interval },
    )
  },
  seek: (ms) => {
    const { video, tick } = get()
    if (video) video.currentTime = ms / 1000
    set({ flippedTo: null })
    tick(ms)
  },
  flip: (slide) => set({ flippedTo: slide }),
  backToVideo: () => set({ flippedTo: null }),
}))

export function nextIntervalShowing(timeline: Interval[], slide: number, fromMs: number): Interval | null {
  const showing = timeline.filter((row) => row.slide === slide)
  return showing.find((row) => row.start_ms > fromMs) ?? showing[0] ?? null
}
