import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import { Link, Navigate, Outlet, Route, Routes, useNavigate } from 'react-router-dom'

import { api, ApiError, type User } from './api/client'
import { AdminCoursePage } from './pages/admin/AdminCourse'
import { AdminCoursesPage } from './pages/admin/AdminCourses'
import { AdminLessonPage } from './pages/admin/AdminLesson'
import { CoursePage, CoursesPage } from './pages/Courses'
import { LessonPage } from './pages/Lesson'
import { LoginPage } from './pages/Login'

const CourseMapPage = lazy(() =>
  import('./pages/CourseMap').then((module) => ({ default: module.CourseMapPage })),
)

function useMe() {
  return useQuery({
    queryKey: ['me'],
    queryFn: () =>
      api<User>('/auth/me').catch((error) => {
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }),
    staleTime: Infinity,
  })
}

function Shell({ admin = false }: { admin?: boolean }) {
  const me = useMe()
  const queries = useQueryClient()
  const navigate = useNavigate()
  const logout = useMutation({
    mutationFn: () => api('/auth/logout', 'POST'),
    onSuccess: () => {
      queries.clear()
      navigate('/login')
    },
  })
  if (me.isPending) return null
  if (!me.data) return <Navigate to="/login" replace />
  if (admin && me.data.role !== 'admin') return <Navigate to="/courses" replace />
  return (
    <div className="shell">
      <header className="topbar">
        <Link className="brand" to="/courses">
          Course Assistant
        </Link>
        <nav>
          {me.data.role === 'admin' && <Link to="/admin/courses">Manage courses</Link>}
          <button type="button" className="link on-dark" onClick={() => logout.mutate()}>
            Log out
          </button>
        </nav>
      </header>
      <Outlet />
    </div>
  )
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<Shell />}>
        <Route path="/courses" element={<CoursesPage />} />
        <Route path="/courses/:id" element={<CoursePage />} />
        <Route
          path="/courses/:id/map"
          element={
            <Suspense fallback={<p className="page-note">Opening the concept map…</p>}>
              <CourseMapPage />
            </Suspense>
          }
        />
        <Route path="/lessons/:id" element={<LessonPage />} />
      </Route>
      <Route element={<Shell admin />}>
        <Route path="/admin/courses" element={<AdminCoursesPage />} />
        <Route path="/admin/courses/:id" element={<AdminCoursePage />} />
        <Route path="/admin/lessons/:id" element={<AdminLessonPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/courses" replace />} />
    </Routes>
  )
}
