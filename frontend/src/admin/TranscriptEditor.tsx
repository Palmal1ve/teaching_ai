import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Virtuoso } from 'react-virtuoso'

import { api, clock, type Player, type Segment } from '../api/client'

function EditableLine({ segment }: { segment: Segment }) {
  const [text, setText] = useState(segment.text)
  const save = useMutation({
    mutationFn: () => api<Segment>(`/admin/segments/${segment.id}`, 'PATCH', { text }),
  })
  return (
    <label className="edit-line">
      <time>{clock(segment.start_ms)}</time>
      <input
        value={text}
        aria-label={`Line at ${clock(segment.start_ms)}`}
        onChange={(event) => setText(event.target.value)}
        onBlur={() => {
          if (text.trim() && text !== segment.text) save.mutate()
        }}
      />
      {save.isSuccess && <span className="saved">Saved</span>}
      {save.isError && <span className="notice">Not saved</span>}
    </label>
  )
}

export function TranscriptEditor({ lessonId, revisionId }: { lessonId: number; revisionId: number }) {
  const player = useQuery({
    queryKey: ['player', lessonId, revisionId],
    queryFn: () => api<Player>(`/lessons/${lessonId}/player?revision_id=${revisionId}`),
  })
  if (!player.data) return null
  return (
    <div className="transcript-editor">
      <Virtuoso
        data={player.data.transcript}
        computeItemKey={(_, segment) => segment.id}
        itemContent={(_, segment) => <EditableLine segment={segment} />}
      />
    </div>
  )
}
