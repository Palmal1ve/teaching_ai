import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, type User } from '../api/client'

export function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const queries = useQueryClient()
  const navigate = useNavigate()
  const enter = (user: User) => {
    queries.setQueryData(['me'], user)
    navigate(user.role === 'admin' ? '/admin/courses' : '/courses')
  }
  const login = useMutation({
    mutationFn: () => api<User>('/auth/login', 'POST', { email, password }),
    onSuccess: enter,
  })
  const demo = useQuery({
    queryKey: ['demo'],
    queryFn: () => api<{ enabled: boolean }>('/auth/demo'),
  })
  const demoLogin = useMutation({
    mutationFn: (role: 'student' | 'admin') => api<User>(`/auth/demo/${role}`, 'POST'),
    onSuccess: enter,
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    login.mutate()
  }
  return (
    <main className="login">
      <form className="book login-book" onSubmit={submit}>
        <div className="book-label">
          <h1 className="book-title">Course Assistant</h1>
          <p className="book-desc">Your recorded classes, and answers that link to the moment.</p>
          <label>
            Email
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {login.isError && <p className="notice" role="alert">{login.error.message}</p>}
          <button type="submit" disabled={login.isPending}>
            Log in
          </button>
          {demo.data?.enabled && (
            <div className="demo-login" role="group" aria-label="Quick demo">
              <span>Quick demo</span>
              <button
                type="button"
                className="quiet"
                disabled={demoLogin.isPending}
                onClick={() => demoLogin.mutate('student')}
              >
                As student
              </button>
              <button
                type="button"
                className="quiet"
                disabled={demoLogin.isPending}
                onClick={() => demoLogin.mutate('admin')}
              >
                As admin
              </button>
              {demoLogin.isError && <p className="notice" role="alert">{demoLogin.error.message}</p>}
            </div>
          )}
        </div>
      </form>
      <figure className="login-shot">
        <img
          src="/player-preview.png"
          width={1600}
          height={1000}
          alt="The lesson player: lecture video, the slide on screen, the synced transcript and an answer citing the second it came from."
        />
      </figure>
    </main>
  )
}
