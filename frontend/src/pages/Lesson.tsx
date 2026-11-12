import { useQuery } from '@tanstack/react-query'
import { Fragment, type ReactNode, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { Group, Panel, type PanelImperativeHandle, Separator } from 'react-resizable-panels'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { api, clock, type Player } from '../api/client'
import { ChatPanel } from '../player/ChatPanel'
import { LayoutPicker } from '../player/LayoutPicker'
import {
  findLayout,
  type FoldableId,
  isFoldable,
  type LayoutId,
  leaves,
  type PanelId,
  readChoice,
  saveChoice,
  type Split,
  withoutSlides,
} from '../player/layouts'
import { usePlayback } from '../player/playbackStore'
import { saveResume } from '../player/resume'
import { SlidePanel } from '../player/SlidePanel'
import { TranscriptPanel } from '../player/TranscriptPanel'
import { VideoPanel } from '../player/VideoPanel'

const NARROW = '(max-width: 899px)'
const SHOWN_KEY = 'player-panels'

type Shown = Record<FoldableId, boolean>

function useNarrow() {
  return useSyncExternalStore(
    (notify) => {
      const query = window.matchMedia(NARROW)
      query.addEventListener('change', notify)
      return () => query.removeEventListener('change', notify)
    },
    () => window.matchMedia(NARROW).matches,
  )
}

function readShown(): Shown {
  try {
    return { transcript: true, chat: true, ...JSON.parse(localStorage.getItem(SHOWN_KEY) ?? '{}') }
  } catch {
    return { transcript: true, chat: true }
  }
}

function useShown() {
  const [shown, setShown] = useState(readShown)
  useEffect(() => {
    try {
      localStorage.setItem(SHOWN_KEY, JSON.stringify(shown))
    } catch {
      // Storage can be refused; the choice still holds for this visit.
    }
  }, [shown])
  return [shown, setShown] as const
}

function Timecode({ duration }: { duration: number }) {
  const second = usePlayback((s) => Math.floor(s.currentMs / 1000))
  return (
    <span className="timecode">
      {clock(second * 1000)}
      <span> / {clock(duration)}</span>
    </span>
  )
}

function Tabs({ player, preview }: { player: Player; preview?: number }) {
  const names = ['Transcript', ...(player.slides.length ? ['Slides'] : []), 'Ask']
  const [tab, setTab] = useState(names[0])
  return (
    <div className="narrow-player">
      <div className="pinned-video">
        <VideoPanel src={player.hls_url} startMs={0} />
      </div>
      <div className="tabs" role="tablist">
        {names.map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={tab === name}
            onClick={() => setTab(name)}
          >
            {name}
          </button>
        ))}
      </div>
      <div className="tab-body">
        {tab === 'Transcript' && <TranscriptPanel segments={player.transcript} />}
        {tab === 'Slides' && <SlidePanel slides={player.slides} />}
        {tab === 'Ask' && <ChatPanel lessonId={player.lesson_id} previewRevision={preview} />}
      </div>
    </div>
  )
}

function Foldable({
  id,
  shown,
  onFolded,
  defaultSize,
  minSize,
  children,
}: {
  id: string
  shown: boolean
  onFolded: () => void
  defaultSize?: string
  minSize: string
  children: ReactNode
}) {
  const ref = useRef<PanelImperativeHandle>(null)
  useEffect(() => {
    const panel = ref.current
    if (!panel) return
    if (shown && panel.isCollapsed()) panel.expand()
    if (!shown && !panel.isCollapsed()) panel.collapse()
  }, [shown])
  return (
    <Panel
      id={id}
      panelRef={ref}
      collapsible
      collapsedSize="0"
      defaultSize={shown ? defaultSize : '0'}
      minSize={minSize}
      onResize={() => {
        if (shown && ref.current?.isCollapsed()) onFolded()
      }}
    >
      <div className="fold" inert={!shown}>
        {children}
      </div>
    </Panel>
  )
}

function Arrangement({
  split,
  shown,
  fold,
  content,
  className,
}: {
  split: Split
  shown: Shown
  fold: (panel: FoldableId) => void
  content: (panel: PanelId) => ReactNode
  className?: string
}) {
  const open = split.items.map((item) => leaves(item).some((panel) => !isFoldable(panel) || shown[panel]))
  const handle = split.split === 'horizontal' ? 'handle' : 'handle horizontal'
  return (
    <Group className={className} orientation={split.split}>
      {split.items.map((item, index) => {
        const panels = leaves(item)
        const folds = panels.filter(isFoldable)
        const id = panels.join('-')
        const size = String(item.size)
        const body =
          'panel' in item ? (
            content(item.panel)
          ) : (
            <Arrangement split={item} shown={shown} fold={fold} content={content} />
          )
        return (
          <Fragment key={id}>
            {index > 0 && (
              <Separator
                className={open[index] && open.slice(0, index).some(Boolean) ? handle : `${handle} gone`}
              />
            )}
            {folds.length === panels.length ? (
              <Foldable
                id={id}
                shown={open[index]}
                onFolded={() => folds.forEach(fold)}
                defaultSize={size}
                minSize="20"
              >
                {body}
              </Foldable>
            ) : (
              <Panel id={id} defaultSize={size} minSize="20">
                {body}
              </Panel>
            )}
          </Fragment>
        )
      })}
    </Group>
  )
}

export function LessonPage() {
  const id = Number(useParams().id)
  const [params] = useSearchParams()
  const preview = Number(params.get('revision')) || undefined
  const startMs = Number(params.get('t')) || 0
  const narrow = useNarrow()
  const [shown, setShown] = useShown()
  const fold = (panel: keyof Shown) => setShown((s) => ({ ...s, [panel]: false }))
  const toggle = (panel: keyof Shown) => setShown((s) => ({ ...s, [panel]: !s[panel] }))
  const [choice, setChoice] = useState(readChoice)
  const [picking, setPicking] = useState(choice.askAtStart)
  const [resume, setResume] = useState({ ms: startMs, play: false })

  useEffect(() => saveChoice(choice), [choice])

  const pick = (layout: LayoutId) => {
    if (layout !== choice.layout) {
      const { video, currentMs } = usePlayback.getState()
      setResume({ ms: currentMs || startMs, play: !!video && !video.paused })
      setChoice((c) => ({ ...c, layout }))
    }
    const solo = !!findLayout(layout).solo
    setShown({ transcript: !solo, chat: !solo })
    setPicking(false)
  }

  const player = useQuery({
    queryKey: ['player', id, preview],
    queryFn: () =>
      api<Player>(`/lessons/${id}/player${preview ? `?revision_id=${preview}` : ''}`),
  })

  useEffect(() => {
    if (player.data) usePlayback.getState().load(player.data.transcript, player.data.timeline)
  }, [player.data])

  useEffect(() => {
    if (preview) return
    const save = () => {
      const ms = usePlayback.getState().currentMs
      if (ms > 0) saveResume(id, ms)
    }
    const timer = window.setInterval(save, 5000)
    return () => {
      window.clearInterval(timer)
      save()
    }
  }, [id, preview])

  if (player.isPending) return <p className="page-note">Opening the lesson…</p>
  if (player.isError) {
    return (
      <p className="page-note" role="alert">
        {player.error.message}. <Link to="/courses">Back to courses</Link>
      </p>
    )
  }

  const data = player.data
  const hasSlides = data.slides.length > 0
  const root = findLayout(choice.layout).root
  const content = (panel: PanelId) =>
    ({
      video: <VideoPanel src={data.hls_url} startMs={resume.ms} autoPlay={resume.play} />,
      transcript: <TranscriptPanel segments={data.transcript} onHide={() => fold('transcript')} />,
      slides: <SlidePanel slides={data.slides} />,
      chat: <ChatPanel lessonId={data.lesson_id} previewRevision={preview} onHide={() => fold('chat')} />,
    })[panel]
  return (
    <main className="lesson">
      <div className="deck-bar">
        <nav className="crumbs" aria-label="Breadcrumb">
          <Link to={`/courses/${data.course_id}`}>{data.course_title}</Link>
          <span aria-hidden="true">/</span>
          <h1>{data.lesson_title}</h1>
        </nav>
        {preview && <span className="tag">Reviewing, not yet published</span>}
        <Timecode duration={data.duration_ms} />
        {!narrow && (
          <div className="panel-toggles" role="group" aria-label="Show panels">
            <button type="button" aria-pressed={shown.transcript} onClick={() => toggle('transcript')}>
              Transcript
            </button>
            <button type="button" aria-pressed={shown.chat} onClick={() => toggle('chat')}>
              Ask
            </button>
          </div>
        )}
        {!narrow && (
          <button type="button" className="layout-button" onClick={() => setPicking(true)}>
            Layout
          </button>
        )}
      </div>
      {narrow ? (
        <Tabs player={data} preview={preview} />
      ) : (
        <Arrangement
          key={choice.layout}
          className="columns"
          split={hasSlides ? root : withoutSlides(root)}
          shown={shown}
          fold={fold}
          content={content}
        />
      )}
      <LayoutPicker
        open={picking && !narrow}
        current={choice.layout}
        hasSlides={hasSlides}
        askAtStart={choice.askAtStart}
        onAskAtStart={(askAtStart) => setChoice((c) => ({ ...c, askAtStart }))}
        onPick={pick}
        onClose={() => setPicking(false)}
      />
    </main>
  )
}
