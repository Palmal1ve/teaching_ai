export type User = { id: number; email: string; role: 'admin' | 'student' }
export type Course = { id: number; title: string; description: string; status: 'draft' | 'published' }
export type Lesson = {
  id: number
  course_id: number
  position: number
  title: string
  status: string
  active_revision_id: number | null
}
export type CourseDetail = Course & { lessons: Lesson[] }
export type CourseLesson = Lesson & { duration_ms: number; concept_count: number }
export type CourseOverview = Course & { lessons: CourseLesson[] }
export type GraphMoment = {
  lesson_id: number
  lesson_title: string
  lesson_position: number
  start_ms: number
  text: string
}
export type GraphNode = {
  id: number
  name: string
  aliases: string[]
  summary: string
  moments: GraphMoment[]
}
export type Graph = {
  course_id: number
  course_title: string
  nodes: GraphNode[]
  edges: { source: number; target: number; type: string }[]
}
export type Segment = { id: number; seq: number; start_ms: number; end_ms: number; text: string }
export type Slide = { id: number; number: number; image_url: string; hidden: boolean }
export type Interval = { start_ms: number; end_ms: number; slide: number | null; estimated: boolean }
export type Player = {
  lesson_id: number
  lesson_title: string
  course_id: number
  course_title: string
  revision_id: number
  hls_url: string | null
  duration_ms: number
  transcript: Segment[]
  slides: Slide[]
  timeline: Interval[]
}
export type Citation = {
  n: number
  lesson_id: number
  start_ms: number
  label: string
  slide: number | null
  quote: string
}
export type Grounding = 'grounded' | 'partial' | 'not_covered'
export type Answer = { message_id: number; text: string; citations: Citation[]; grounding: Grounding }
export type Message = {
  id: number
  role: 'user' | 'assistant'
  text: string
  citations: Citation[]
  grounding: Grounding | null
}
export type Stage = { name: string; status: string; attempts: number; error: string | null }
export type Revision = {
  id: number
  status: string
  has_deck: boolean
  transcript_file: string | null
  active: boolean
  stages: Stage[]
}
export type UnsavedFile = { kind: 'video' | 'deck' | 'transcript'; filename: string }
export type LessonAdmin = Lesson & { revisions: Revision[]; unsaved: UnsavedFile[] }
export type TimelineRow = {
  start_ms: number
  end_ms: number
  slide: number | null
  confidence: number
  method: 'visual' | 'speech'
  source: 'auto' | 'manual'
}
export type Timeline = { duration_ms: number; rows: TimelineRow[]; slides: Slide[] }
export type UploadPart = { part_number: number; url: string }
export type UploadStart = { upload_id: number; part_size: number; parts: UploadPart[] }
export type UploadState = UploadStart & {
  done: { part_number: number; size: number; etag: string }[]
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly code?: string,
  ) {
    super(message)
  }
}

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    method,
    credentials: 'same-origin',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (response.status === 204) return undefined as T
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : `Request failed (${response.status})`
    throw new ApiError(response.status, detail, data?.code)
  }
  return data as T
}

export function clock(ms: number): string {
  const seconds = Math.floor(ms / 1000)
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const rest = String(seconds % 60).padStart(2, '0')
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`
}
