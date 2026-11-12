import { useEffect, useState } from 'react'

import type { Revision } from './client'

const FINISHED = ['superseded', 'published']

export function useRevisionEvents(revisionId: number | undefined): Revision | null {
  const [revision, setRevision] = useState<Revision | null>(null)
  useEffect(() => {
    setRevision(null)
    if (!revisionId) return
    const source = new EventSource(`/api/v1/admin/revisions/${revisionId}/events`)
    source.onmessage = (event) => {
      const next: Revision = JSON.parse(event.data)
      setRevision(next)
      if (FINISHED.includes(next.status)) source.close()
    }
    return () => source.close()
  }, [revisionId])
  return revision
}
