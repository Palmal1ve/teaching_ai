import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { api, clock, type Course, type CourseOverview } from '../api/client'
import { readResume } from '../player/resume'

export function CoursesPage() {
  const courses = useQuery({ queryKey: ['courses'], queryFn: () => api<Course[]>('/courses') })
  return (
    <main className="page">
      <h1 className="page-title">Your courses</h1>
      {courses.isPending && (
        <ul className="bin" aria-label="Loading courses">
          {[0, 1, 2].map((row) => (
            <li key={row}>
              <span className="skeleton" />
              <span className="skeleton short" />
            </li>
          ))}
        </ul>
      )}
      {courses.isError && <p className="notice" role="alert">{courses.error.message}</p>}
      {courses.data?.length === 0 && (
        <p className="page-note">No courses are published yet. An admin publishes them here.</p>
      )}
      <ul className="bin">
        {courses.data?.map((course) => (
          <li key={course.id}>
            <Link to={`/courses/${course.id}`}>
              <span className="bin-title">{course.title}</span>
              {course.description && <span className="bin-desc">{course.description}</span>}
            </Link>
          </li>
        ))}
      </ul>
    </main>
  )
}

export function CoursePage() {
  const id = Number(useParams().id)
  const course = useQuery({
    queryKey: ['course', id],
    queryFn: () => api<CourseOverview>(`/courses/${id}`),
  })
  if (course.isPending) return <p className="page-note">Opening the course…</p>
  if (course.isError) return <p className="page-note" role="alert">{course.error.message}</p>

  const { lessons } = course.data
  const total = lessons.reduce((sum, lesson) => sum + lesson.duration_ms, 0)
  return (
    <main className="page">
      <nav className="crumbs plain" aria-label="Breadcrumb">
        <Link to="/courses">Courses</Link>
      </nav>
      <div className="course-head">
        <div>
          <h1 className="page-title">{course.data.title}</h1>
          {course.data.description && <p className="lede">{course.data.description}</p>}
          {lessons.length > 0 && (
            <p className="course-facts">
              {lessons.length} {lessons.length === 1 ? 'lesson' : 'lessons'} · {clock(total)} of video
            </p>
          )}
        </div>
        {lessons.length > 0 && (
          <Link className="button quiet" to={`/courses/${id}/map`}>
            Concept map
          </Link>
        )}
      </div>
      {lessons.length === 0 ? (
        <p className="page-note">No lessons are published in this course yet.</p>
      ) : (
        <table className="lesson-table">
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Lesson</th>
              <th scope="col">Length</th>
              <th scope="col">Concepts</th>
              <th scope="col">
                <span className="visually-hidden">Resume</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {lessons.map((lesson) => {
              const resume = readResume(lesson.id)
              return (
                <tr key={lesson.id}>
                  <td className="lesson-pos">{lesson.position}</td>
                  <td>
                    <Link className="lesson-link" to={`/lessons/${lesson.id}`}>
                      {lesson.title}
                    </Link>
                  </td>
                  <td className="lesson-num">{lesson.duration_ms ? clock(lesson.duration_ms) : '–'}</td>
                  <td className="lesson-num">{lesson.concept_count}</td>
                  <td className="lesson-resume">
                    {resume && (
                      <Link to={`/lessons/${lesson.id}?t=${resume}`}>
                        <span className="marked">Resume at {clock(resume)}</span>
                      </Link>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </main>
  )
}
