import { useEffect } from 'react'

import type { Slide } from '../api/client'
import { nextIntervalShowing, usePlayback } from './playbackStore'

export function SlidePanel({ slides }: { slides: Slide[] }) {
  const flippedTo = usePlayback((s) => s.flippedTo)
  const interval = usePlayback((s) => s.timeline[s.activeInterval])
  const number = flippedTo ?? interval?.slide ?? null
  const following = flippedTo === null
  const slide = slides.find((s) => s.number === number)
  const visible = slides.filter((s) => !s.hidden || s.number === number)
  const position = visible.findIndex((s) => s.number === number)

  useEffect(() => {
    for (const neighbour of [visible[position - 1], visible[position + 1]]) {
      if (neighbour) new Image().src = neighbour.image_url
    }
  }, [visible, position])

  const flipBy = (step: number) => {
    const fallback = step > 0 ? visible[0] : visible[visible.length - 1]
    const target = position < 0 ? fallback : visible[position + step]
    if (target) usePlayback.getState().flip(target.number)
  }

  const findDiscussion = () => {
    if (number === null) return
    const { timeline, currentMs, seek } = usePlayback.getState()
    const found = nextIntervalShowing(timeline, number, currentMs)
    if (found) seek(found.start_ms)
  }

  const discussed = number !== null && usePlayback.getState().timeline.some((t) => t.slide === number)

  return (
    <section className="panel slides" aria-label="Slides">
      <header className="panel-head">
        <h2>{slide ? `Slide ${slide.number} of ${slides.length}` : 'Slides'}</h2>
        {following && interval?.estimated && slide && (
          <span className="tag" title="Worked out from what the professor said, not from the picture">
            Estimated
          </span>
        )}
      </header>
      <div className="slide-stage">
        {slide ? (
          <img src={slide.image_url} alt={`Slide ${slide.number}`} />
        ) : (
          <p className="panel-note">The professor is away from the slides here.</p>
        )}
      </div>
      <footer className="slide-controls">
        <button type="button" className="quiet" onClick={() => flipBy(-1)} disabled={position === 0}>
          Previous
        </button>
        {following ? (
          <span className="following">Following the video</span>
        ) : (
          <button type="button" onClick={() => usePlayback.getState().backToVideo()}>
            Back to video
          </button>
        )}
        <button
          type="button"
          className="quiet"
          onClick={() => flipBy(1)}
          disabled={position === visible.length - 1}
        >
          Next
        </button>
      </footer>
      {!following && discussed && (
        <button type="button" className="link discussed" onClick={findDiscussion}>
          Where was this discussed?
        </button>
      )}
    </section>
  )
}
