import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api, type CourseDetail, type Lesson } from '../../api/client'

const STATUS_LABELS: Record<string, string> = {
  draft: 'Needs a video',
  processing: 'Processing',
  needs_review: 'Ready for review',
  published: 'Published',
  failed: 'Failed',
}

export function AdminCoursePage() {
  const id = Number(useParams().id)
  const queries = useQueryClient()
  const navigate = useNavigate()
  const [title, setTitle] = useState('')
  const key = ['admin-course', id]
  const course = useQuery({
    queryKey: key,
    queryFn: () => api<CourseDetail>(`/admin/courses/${id}`),
  })
  const refresh = () => queries.invalidateQueries({ queryKey: key })

  const addLesson = useMutation({
    mutationFn: () => api<Lesson>('/admin/lessons', 'POST', { course_id: id, title }),
    onSuccess: () => {
      setTitle('')
      refresh()
    },
  })
  const setStatus = useMutation({
    mutationFn: (status: string) => api(`/admin/courses/${id}`, 'PATCH', { status }),
    onSuccess: refresh,
  })
  const swap = useMutation({
    mutationFn: async ([a, b]: [Lesson, Lesson]) => {
      await api(`/admin/lessons/${a.id}`, 'PATCH', { position: b.position })
      await api(`/admin/lessons/${b.id}`, 'PATCH', { position: a.position })
    },
    onSuccess: refresh,
  })
  const deleteCourse = useMutation({
    mutationFn: () => api(`/admin/courses/${id}`, 'DELETE'),
    onSuccess: () => {
      queries.invalidateQueries({ queryKey: ['admin-courses'] })
      navigate('/admin/courses')
    },
  })

  if (course.isPending) return <p className="page-note">Opening the course…</p>
  if (course.isError) return <p className="page-note" role="alert">{course.error.message}</p>

  const data = course.data
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (title.trim()) addLesson.mutate()
  }
  const published = data.status === 'published'

  return (
    <main className="page">
      <nav className="crumbs plain" aria-label="Breadcrumb">
        <Link to="/admin/courses">Manage courses</Link>
      </nav>
      <h1 className="page-title">{data.title}</h1>
      <div className="actions">
        <button type="button" onClick={() => setStatus.mutate(published ? 'draft' : 'published')}>
          {published ? 'Unpublish course' : 'Publish course'}
        </button>
        <button
          type="button"
          className="danger"
          onClick={() => {
            if (window.confirm(`Delete “${data.title}” and all its lessons? This cannot be undone.`)) {
              deleteCourse.mutate()
            }
          }}
        >
          Delete course
        </button>
      </div>

      <h2 className="section-title">Lessons</h2>
      <form className="row-form" onSubmit={submit}>
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Lesson 1: Shortest paths"
          aria-label="New lesson title"
        />
        <button type="submit" disabled={!title.trim() || addLesson.isPending}>
          Add lesson
        </button>
      </form>
      {data.lessons.length === 0 && <p className="page-note">Add a lesson, then upload its video.</p>}
      <ol className="admin-list">
        {data.lessons.map((lesson, index) => (
          <li key={lesson.id}>
            <span className="position">{lesson.position}</span>
            <Link to={`/admin/lessons/${lesson.id}`}>{lesson.title}</Link>
            <span className={`tag ${lesson.status}`}>
              {STATUS_LABELS[lesson.status] ?? lesson.status}
            </span>
            <span className="reorder">
              <button
                type="button"
                className="quiet"
                aria-label={`Move ${lesson.title} up`}
                disabled={index === 0}
                onClick={() => swap.mutate([lesson, data.lessons[index - 1]])}
              >
                ↑
              </button>
              <button
                type="button"
                className="quiet"
                aria-label={`Move ${lesson.title} down`}
                disabled={index === data.lessons.length - 1}
                onClick={() => swap.mutate([lesson, data.lessons[index + 1]])}
              >
                ↓
              </button>
            </span>
          </li>
        ))}
      </ol>
    </main>
  )
}
