import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { Virtuoso, type VirtuosoHandle } from 'react-virtuoso'

import { clock, type Interval, type Segment } from '../api/client'
import { usePlayback } from './playbackStore'

const SCROLL_PAUSE_MS = 8000

/** Slide number to announce on the first line spoken after each slide change. */
export function slideCuts(segments: Segment[], timeline: Interval[]): Map<number, number> {
  const cuts = new Map<number, number>()
  for (const interval of timeline) {
    if (interval.slide === null) continue
    const first = segments.find((s) => s.start_ms >= interval.start_ms)
    if (first && first.start_ms < interval.end_ms) cuts.set(first.id, interval.slide)
  }
  return cuts
}

const Line = memo(function Line({ segment, cut }: { segment: Segment; cut?: number }) {
  const active = usePlayback((s) => s.transcript[s.activeLine]?.id === segment.id)
  return (
    <button
      type="button"
      className="line"
      aria-current={active || undefined}
      onClick={() => usePlayback.getState().seek(segment.start_ms)}
    >
      <time className="line-time">{clock(segment.start_ms)}</time>
      <span className="line-text">
        {cut !== undefined && <span className="cut">Slide {cut}</span>}
        <span className={active ? 'marked swipe' : undefined}>{segment.text}</span>
      </span>
    </button>
  )
})

export function TranscriptPanel({ segments, onHide }: { segments: Segment[]; onHide?: () => void }) {
  const [search, setSearch] = useState('')
  const list = useRef<VirtuosoHandle>(null)
  const pausedUntil = useRef(0)
  const activeLine = usePlayback((s) => s.activeLine)
  const timeline = usePlayback((s) => s.timeline)
  const cuts = useMemo(() => slideCuts(segments, timeline), [segments, timeline])

  const shown = useMemo(() => {
    const term = search.trim().toLowerCase()
    return term ? segments.filter((s) => s.text.toLowerCase().includes(term)) : segments
  }, [segments, search])

  useEffect(() => {
    if (search || activeLine < 0 || Date.now() < pausedUntil.current) return
    list.current?.scrollToIndex({ index: activeLine, align: 'center', behavior: 'auto' })
  }, [activeLine, search])

  const pause = () => {
    pausedUntil.current = Date.now() + SCROLL_PAUSE_MS
  }

  return (
    <section className="panel transcript" aria-label="Transcript">
      <header className="panel-head">
        <h2>Transcript</h2>
        <input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search this lecture"
          aria-label="Search the transcript"
        />
        {onHide && (
          <button type="button" className="hide" onClick={onHide}>
            Hide
          </button>
        )}
      </header>
      {shown.length === 0 ? (
        <p className="panel-note">
          {search ? `Nothing in this lecture matches “${search}”.` : 'No transcript yet.'}
        </p>
      ) : (
        <div className="ruled" onWheel={pause} onTouchMove={pause}>
          <Virtuoso
            ref={list}
            data={shown}
            computeItemKey={(_, segment) => segment.id}
            itemContent={(_, segment) => <Line segment={segment} cut={cuts.get(segment.id)} />}
          />
        </div>
      )}
    </section>
  )
}
