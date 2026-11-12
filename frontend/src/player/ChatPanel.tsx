import { useMutation, useQuery } from '@tanstack/react-query'
import { type FormEvent, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  type Answer,
  api,
  ApiError,
  type Citation,
  type Grounding,
  type Message,
} from '../api/client'
import { AnswerMarkdown } from './AnswerMarkdown'
import { splitBeyond } from './answerText'
import { usePlayback } from './playbackStore'

type Entry = { key: string; role: 'user' | 'assistant' } & Partial<
  Pick<Answer, 'citations' | 'grounding'>
> & { text: string }

const BADGES: Record<Grounding, string> = {
  grounded: 'From this class',
  partial: 'Partly from this class',
  not_covered: 'Not covered in class',
}

function CitationChip({ citation, lessonId }: { citation: Citation; lessonId: number }) {
  const navigate = useNavigate()
  const open = () => {
    if (citation.lesson_id === lessonId) usePlayback.getState().seek(citation.start_ms)
    else navigate(`/lessons/${citation.lesson_id}?t=${citation.start_ms}`)
  }
  const elsewhere = citation.lesson_id !== lessonId
  return (
    <button type="button" className="cite" onClick={open} title={citation.quote}>
      <span className="marked">
        {citation.label}
        {citation.slide !== null && ` · slide ${citation.slide}`}
        {elsewhere && ' · other lesson'}
      </span>
    </button>
  )
}

function AssistantMessage({ entry, lessonId }: { entry: Entry; lessonId: number }) {
  const { fromClass, beyond } = splitBeyond(entry.text)
  const citations = entry.citations ?? []
  const chip = (n: number) => {
    const citation = citations.find((c) => c.n === n)
    return citation && <CitationChip citation={citation} lessonId={lessonId} />
  }
  return (
    <article className="answer">
      {entry.grounding && <p className={`badge ${entry.grounding}`}>{BADGES[entry.grounding]}</p>}
      {fromClass && (
        <AnswerMarkdown text={fromClass} citations={citations.map((c) => c.n)} chip={chip} />
      )}
      {beyond && (
        <aside className="beyond">
          <h3>Beyond the class material</h3>
          <AnswerMarkdown text={beyond} />
        </aside>
      )}
    </article>
  )
}

function savedChat(lessonId: number): number | null {
  try {
    return Number(localStorage.getItem(`chat:${lessonId}`)) || null
  } catch {
    return null
  }
}

function saveChat(lessonId: number, id: number) {
  try {
    localStorage.setItem(`chat:${lessonId}`, String(id))
  } catch {
    // Private windows can refuse storage. The chat still works for this visit.
  }
}

async function openChat(lessonId: number, previewRevision?: number) {
  const saved = previewRevision ? null : savedChat(lessonId)
  if (saved) {
    const messages = await api<Message[]>(`/chat/sessions/${saved}/messages`).catch(() => null)
    if (messages) {
      const entries: Entry[] = messages.map((m) => ({
        key: `m${m.id}`,
        role: m.role,
        text: m.text,
        citations: m.citations,
        grounding: m.grounding ?? undefined,
      }))
      return { id: saved, entries }
    }
  }
  const { id } = await api<{ id: number }>(`/lessons/${lessonId}/chat/sessions`, 'POST', {
    revision_id: previewRevision ?? null,
  })
  if (!previewRevision) saveChat(lessonId, id)
  return { id, entries: [] as Entry[] }
}

export function ChatPanel({
  lessonId,
  previewRevision,
  onHide,
}: {
  lessonId: number
  previewRevision?: number
  onHide?: () => void
}) {
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [entries, setEntries] = useState<Entry[]>([])
  const [draft, setDraft] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const end = useRef<HTMLDivElement>(null)

  const started = useQuery({
    queryKey: ['chat-session', lessonId, previewRevision],
    queryFn: () => openChat(lessonId, previewRevision),
    staleTime: Infinity,
    gcTime: 0,
  })

  useEffect(() => {
    setEntries(started.data?.entries ?? [])
    setSessionId(started.data?.id ?? null)
  }, [started.data])

  const ask = useMutation({
    mutationFn: (text: string) =>
      api<Answer>(`/chat/sessions/${sessionId}/messages`, 'POST', {
        text,
        current_time_ms: Math.floor(usePlayback.getState().currentMs),
        revision_id: previewRevision ?? null,
      }),
    onMutate: (text) => {
      setNotice(null)
      setEntries((rows) => [...rows, { key: `q${rows.length}`, role: 'user', text }])
    },
    onSuccess: (answer) =>
      setEntries((rows) => [...rows, { ...answer, key: `a${answer.message_id}`, role: 'assistant' }]),
    onError: (error) => {
      const offline = error instanceof ApiError && error.code === 'assistant_offline'
      setNotice(
        offline
          ? 'Assistant offline. Video, transcript and slides still work. Try your question again later.'
          : error.message,
      )
    },
  })

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [entries, ask.isPending])

  const send = (event: FormEvent) => {
    event.preventDefault()
    const text = draft.trim()
    if (!text || !sessionId || ask.isPending) return
    setDraft('')
    ask.mutate(text)
  }

  return (
    <section className="panel chat" aria-label="AI assistant">
      <header className="panel-head">
        <h2>Ask about this class</h2>
        {onHide && (
          <button type="button" className="hide" onClick={onHide}>
            Hide
          </button>
        )}
      </header>
      <div className="chat-log" aria-live="polite">
        {entries.length === 0 && !ask.isPending && (
          <p className="panel-note">
            Ask what the professor said, or what this slide means. Answers link to the moment in the
            video.
          </p>
        )}
        {entries.map((entry) =>
          entry.role === 'user' ? (
            <p key={entry.key} className="question">
              {entry.text}
            </p>
          ) : (
            <AssistantMessage key={entry.key} entry={entry} lessonId={lessonId} />
          ),
        )}
        {ask.isPending && <p className="panel-note">Reading the class material…</p>}
        {notice && (
          <p className="notice" role="alert">
            {notice}
          </p>
        )}
        <div ref={end} />
      </div>
      <form className="chat-form" onSubmit={send}>
        <textarea
          rows={2}
          value={draft}
          maxLength={2000}
          aria-label="Your question"
          placeholder="Why did we relax the edges twice?"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) send(event)
          }}
        />
        <button type="submit" disabled={!draft.trim() || !sessionId || ask.isPending}>
          Ask
        </button>
      </form>
    </section>
  )
}
