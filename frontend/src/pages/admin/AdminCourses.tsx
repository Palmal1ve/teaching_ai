import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Link } from 'react-router-dom'

import { api, type Course } from '../../api/client'

export function AdminCoursesPage() {
  const queries = useQueryClient()
  const [title, setTitle] = useState('')
  const courses = useQuery({
    queryKey: ['admin-courses'],
    queryFn: () => api<Course[]>('/admin/courses'),
  })
  const create = useMutation({
    mutationFn: () => api<Course>('/admin/courses', 'POST', { title }),
    onSuccess: () => {
      setTitle('')
      queries.invalidateQueries({ queryKey: ['admin-courses'] })
    },
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (title.trim()) create.mutate()
  }
  return (
    <main className="page">
      <h1 className="page-title">Manage courses</h1>
      <form className="row-form" onSubmit={submit}>
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Algorithms 101"
          aria-label="New course title"
        />
        <button type="submit" disabled={!title.trim() || create.isPending}>
          Create course
        </button>
      </form>
      {create.isError && <p className="notice" role="alert">{create.error.message}</p>}
      {courses.data?.length === 0 && <p className="page-note">Create your first course above.</p>}
      <ul className="admin-list">
        {courses.data?.map((course) => (
          <li key={course.id}>
            <Link to={`/admin/courses/${course.id}`}>{course.title}</Link>
            <span className={`tag ${course.status}`}>{course.status}</span>
          </li>
        ))}
      </ul>
    </main>
  )
}
