import { describe, expect, it } from 'vitest'

import { slideCuts } from './TranscriptPanel'

const seg = (id: number, start_ms: number) => ({ id, seq: id, start_ms, end_ms: start_ms + 4000, text: '' })
const span = (start_ms: number, end_ms: number, slide: number | null) => ({ start_ms, end_ms, slide, estimated: false })

describe('slideCuts', () => {
  it('marks the first line spoken after each slide change', () => {
    const segments = [seg(1, 0), seg(2, 5000), seg(3, 10000), seg(4, 16000)]
    const cuts = slideCuts(segments, [span(0, 6000, 1), span(6000, 16000, 2), span(16000, 20000, null)])
    expect([...cuts]).toEqual([[1, 1], [3, 2]])
  })

  it('skips a slide shown while nobody spoke', () => {
    const cuts = slideCuts([seg(1, 0), seg(2, 9000)], [span(0, 3000, 1), span(3000, 8000, 2), span(8000, 12000, 3)])
    expect([...cuts]).toEqual([[1, 1], [2, 3]])
  })
})
