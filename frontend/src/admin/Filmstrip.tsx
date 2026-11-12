import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from 'react'

import { api, clock, type Timeline, type TimelineRow } from '../api/client'
import { LOW_CONFIDENCE, moveBoundary, reassign, split } from './timelineEdits'

const PIXELS_PER_MINUTE = 70

export function Filmstrip({ revisionId }: { revisionId: number }) {
  const queries = useQueryClient()
  const key = ['timeline', revisionId]
  const timeline = useQuery({
    queryKey: key,
    queryFn: () => api<Timeline>(`/admin/revisions/${revisionId}/timeline`),
  })
  const [rows, setRows] = useState<TimelineRow[]>([])
  const [selected, setSelected] = useState(0)
  const [dirty, setDirty] = useState(false)
  const strip = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (timeline.data) {
      setRows(timeline.data.rows)
      setDirty(false)
    }
  }, [timeline.data])

  const save = useMutation({
    mutationFn: () => api(`/admin/revisions/${revisionId}/timeline`, 'PUT', { rows }),
    onSuccess: () => queries.invalidateQueries({ queryKey: key }),
  })

  if (!timeline.data) return null
  const { duration_ms: duration, slides } = timeline.data
  if (slides.length === 0) return <p className="page-note">This lesson has no slides to correct.</p>

  const edit = (next: TimelineRow[]) => {
    setRows(next)
    setDirty(true)
  }

  const drag = (index: number) => (start: ReactPointerEvent) => {
    start.preventDefault()
    const bar = strip.current!
    const move = (event: PointerEvent) => {
      const box = bar.getBoundingClientRect()
      setRows((current) =>
        moveBoundary(current, index, ((event.clientX - box.left) / box.width) * duration),
      )
      setDirty(true)
    }
    const stop = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop)
  }

  const current = rows[selected]
  const image = (number: number | null) => slides.find((s) => s.number === number)?.image_url
  const low = rows.filter((row) => row.confidence < LOW_CONFIDENCE).length

  return (
    <div className="filmstrip">
      <p className="panel-note">
        {low
          ? `${low} ${low === 1 ? 'span is' : 'spans are'} low confidence, marked in red. Check those first.`
          : 'All spans are high confidence. Spot-check a few, then publish.'}
      </p>
      <div className="strip-scroll">
        <div
          className="strip"
          ref={strip}
          style={{ width: Math.max((duration / 60000) * PIXELS_PER_MINUTE, 600) }}
        >
          {rows.map((row, index) => (
            <div
              key={`${index}-${row.start_ms}`}
              className="span-wrap"
              style={{ width: `${((row.end_ms - row.start_ms) / duration) * 100}%` }}
            >
              <button
                type="button"
                className={[
                  'span',
                  index === selected ? 'selected' : '',
                  row.confidence < LOW_CONFIDENCE ? 'low' : '',
                ].join(' ')}
                style={image(row.slide) ? { backgroundImage: `url(${image(row.slide)})` } : undefined}
                onClick={() => setSelected(index)}
                aria-label={`${clock(row.start_ms)} to ${clock(row.end_ms)}, ${
                  row.slide === null ? 'no slide' : `slide ${row.slide}`
                }`}
              >
                <span>{row.slide ?? 'off'}</span>
              </button>
              {index < rows.length - 1 && (
                <span
                  className="boundary"
                  role="separator"
                  aria-label="Drag to move this slide change"
                  onPointerDown={drag(index)}
                />
              )}
            </div>
          ))}
        </div>
      </div>

      {current && (
        <div className="span-detail">
          <p>
            <strong>
              {clock(current.start_ms)} to {clock(current.end_ms)}
            </strong>{' '}
            {current.method === 'speech' && current.source === 'auto' && 'Estimated from speech. '}
            {current.source === 'manual' && 'Corrected by hand. '}
            Confidence {Math.round(current.confidence * 100)}%.
          </p>
          <div className="choices" role="group" aria-label="Show this slide during the span">
            <button
              type="button"
              className="quiet"
              aria-pressed={current.slide === null}
              onClick={() => edit(reassign(rows, selected, null))}
            >
              No slide
            </button>
            {slides.map((slide) => (
              <button
                key={slide.id}
                type="button"
                className="choice"
                aria-pressed={current.slide === slide.number}
                aria-label={`Slide ${slide.number}`}
                onClick={() => edit(reassign(rows, selected, slide.number))}
              >
                <img src={slide.image_url} alt="" loading="lazy" />
                <span>{slide.number}</span>
              </button>
            ))}
          </div>
          <button type="button" className="quiet" onClick={() => edit(split(rows, selected))}>
            Split this span in two
          </button>
        </div>
      )}

      <div className="actions">
        <button type="button" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
          Save timeline
        </button>
        {save.isError && <span className="notice" role="alert">{save.error.message}</span>}
        {save.isSuccess && !dirty && <span className="saved">Saved</span>}
      </div>
    </div>
  )
}
