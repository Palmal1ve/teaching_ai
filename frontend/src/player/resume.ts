const key = (lessonId: number) => `resume:${lessonId}`

export function saveResume(lessonId: number, ms: number) {
  try {
    localStorage.setItem(key(lessonId), String(Math.floor(ms)))
  } catch {
    // Storage can be refused; resuming is a convenience.
  }
}

export function readResume(lessonId: number): number | null {
  try {
    return Number(localStorage.getItem(key(lessonId))) || null
  } catch {
    return null
  }
}
