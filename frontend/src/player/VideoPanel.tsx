import Hls from 'hls.js'
import { useEffect, useRef } from 'react'

import { usePlayback } from './playbackStore'

export function VideoPanel({ src, startMs, autoPlay }: { src: string | null; startMs: number; autoPlay?: boolean }) {
  const element = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    const video = element.current
    if (!video || !src) return
    const { attach, tick } = usePlayback.getState()
    attach(video)
    const update = () => tick(video.currentTime * 1000)
    const begin = () => {
      if (startMs) usePlayback.getState().seek(startMs)
      if (autoPlay) video.play().catch(() => {})
    }
    video.addEventListener('timeupdate', update)
    video.addEventListener('seeked', update)
    video.addEventListener('loadedmetadata', begin, { once: true })

    let hls: Hls | undefined
    if (Hls.isSupported()) {
      hls = new Hls()
      hls.loadSource(src)
      hls.attachMedia(video)
    } else {
      video.src = src
    }
    return () => {
      video.removeEventListener('timeupdate', update)
      video.removeEventListener('seeked', update)
      hls?.destroy()
      attach(null)
    }
  }, [src, startMs, autoPlay])

  if (!src) return <div className="video-empty">This video is still being prepared.</div>
  return <video ref={element} className="video" controls playsInline aria-label="Lecture video" />
}
