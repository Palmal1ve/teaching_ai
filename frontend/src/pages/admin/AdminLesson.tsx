import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { Filmstrip } from '../../admin/Filmstrip'
import { StageList } from '../../admin/StageList'
import { TranscriptEditor } from '../../admin/TranscriptEditor'
import { type UploadKind, Uploader } from '../../admin/Uploader'
import { api, type LessonAdmin, type Revision } from '../../api/client'
import { useRevisionEvents } from '../../api/sse'

const REVIEWABLE = ['needs_review', 'published']

const UPLOADS: [UploadKind, string][] = [
  ['video', 'Video'],
  ['deck', 'Presentation'],
  ['transcript', 'Transcript'],
]
const LABELS = Object.fromEntries(UPLOADS) as Record<UploadKind, string>

const SUMMARY: Record<string, string> = {
  processing: 'Processing. You can leave this page, it keeps running.',
  failed: 'A stage failed. Retry it, or upload a corrected file.',
  needs_review: 'Ready for review. Students see nothing until you publish.',
  published: 'Published.',
}

function Review({ lessonId, revision }: { lessonId: number; revision: Revision }) {
  const queries = useQueryClient()
  const publish = useMutation({
    mutationFn: () => api(`/admin/revisions/${revision.id}/publish`, 'POST'),
    onSuccess: () => queries.invalidateQueries({ queryKey: ['admin-lesson', lessonId] }),
  })
  return (
    <>
      <h2 className="section-title">Review</h2>
      <div className="actions">
        <Link className="button quiet" to={`/lessons/${lessonId}?revision=${revision.id}`}>
          Watch as a student
        </Link>
        {!revision.active && (
          <button type="button" disabled={publish.isPending} onClick={() => publish.mutate()}>
            Publish
          </button>
        )}
        {revision.active && <span className="saved">This version is live</span>}
        {publish.isError && <span className="notice" role="alert">{publish.error.message}</span>}
      </div>
      {revision.has_deck && (
        <>
          <h3 className="sub-title">Slide timeline</h3>
          <Filmstrip revisionId={revision.id} />
        </>
      )}
      <h3 className="sub-title">Transcript</h3>
      <TranscriptEditor lessonId={lessonId} revisionId={revision.id} />
    </>
  )
}

export function AdminLessonPage() {
  const id = Number(useParams().id)
  const queries = useQueryClient()
  const navigate = useNavigate()
  const key = ['admin-lesson', id]
  const lesson = useQuery({
    queryKey: key,
    queryFn: () => api<LessonAdmin>(`/admin/lessons/${id}`),
  })
  const newest = lesson.data?.revisions[0]
  const live = useRevisionEvents(newest?.id)
  const revision = live ?? newest
  const status = revision?.status

  useEffect(() => {
    if (status && status !== newest?.status) queries.invalidateQueries({ queryKey: key })
    // eslint-disable-next-line
  }, [status])

  const [busy, setBusy] = useState<Partial<Record<UploadKind, boolean>>>({})
  const uploading = Object.values(busy).some(Boolean)
  const save = useMutation({
    mutationFn: () => api(`/admin/lessons/${id}/save`, 'POST'),
    onSuccess: () => queries.invalidateQueries({ queryKey: key }),
  })

  const remove = useMutation({
    mutationFn: () => api(`/admin/lessons/${id}`, 'DELETE'),
    onSuccess: () => navigate(`/admin/courses/${lesson.data?.course_id}`),
  })

  if (lesson.isPending) return <p className="page-note">Opening the lesson…</p>
  if (lesson.isError) return <p className="page-note" role="alert">{lesson.error.message}</p>
  const data = lesson.data

  return (
    <main className="page wide">
      <nav className="crumbs plain" aria-label="Breadcrumb">
        <Link to={`/admin/courses/${data.course_id}`}>Back to course</Link>
      </nav>
      <h1 className="page-title">{data.title}</h1>

      <h2 className="section-title">{newest ? 'Replace files' : 'Upload files'}</h2>
      {newest && (
        <p className="panel-note">
          Uploading only a new deck or transcript keeps the streaming files. The live version stays
          up until you publish the new one.
        </p>
      )}
      <div className="upload-grid">
        {UPLOADS.map(([kind, label]) => (
          <section key={kind} aria-label={label}>
            <h3 className="sub-title">{label}</h3>
            <Uploader
              key={`${id}-${kind}`}
              lessonId={id}
              kind={kind}
              onFinished={() => queries.invalidateQueries({ queryKey: key })}
              onBusy={(isBusy) => setBusy((current) => ({ ...current, [kind]: isBusy }))}
            />
          </section>
        ))}
      </div>
      <div className="actions">
        <button
          type="button"
          disabled={uploading || data.unsaved.length === 0 || save.isPending}
          onClick={() => save.mutate()}
        >
          Save
        </button>
        <span className="panel-note">
          {uploading
            ? 'Wait for the uploads to finish, then save.'
            : data.unsaved.length
              ? `Not saved yet: ${data.unsaved.map((f) => `${LABELS[f.kind]} (${f.filename})`).join(', ')}. Save starts processing.`
              : 'Upload files in any order, then save to start processing.'}
        </span>
        {save.isError && (
          <span className="notice" role="alert">
            {save.error.message}
          </span>
        )}
      </div>

      {revision && (
        <>
          <h2 className="section-title">Progress</h2>
          <p className="panel-note">{SUMMARY[revision.status] ?? revision.status}</p>
          <p className="panel-note">
            {revision.transcript_file
              ? `Transcript from ${revision.transcript_file}.`
              : 'Transcript from speech recognition.'}
          </p>
          <StageList revision={revision} />
        </>
      )}

      {revision && REVIEWABLE.includes(revision.status) && (
        <Review lessonId={id} revision={revision} />
      )}

      <div className="actions end">
        <button
          type="button"
          className="danger"
          onClick={() => {
            if (window.confirm(`Delete “${data.title}”? This cannot be undone.`)) remove.mutate()
          }}
        >
          Delete lesson
        </button>
      </div>
    </main>
  )
}
