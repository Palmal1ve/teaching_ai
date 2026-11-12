import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph3D, { type ForceGraphMethods, type NodeObject } from 'react-force-graph-3d'
import { Link, useParams } from 'react-router-dom'
import SpriteText from 'three-spritetext'

import { api, clock, type Graph, type GraphNode } from '../api/client'
import { EDGE_TYPES, neighbours, relations } from '../map/relations'

type Node = NodeObject<GraphNode>
type Methods = ForceGraphMethods<Node>

const FADED = 'rgba(138, 153, 173, 0.18)'
const LABEL = '#e8eff5'
const LABEL_FADED = 'rgba(232, 239, 245, 0.25)'

const size = (node: GraphNode) => Math.min(1 + node.moments.length, 8)
const radius = (node: GraphNode) => 4 * Math.cbrt(size(node))
const endId = (end: unknown) => (typeof end === 'object' ? (end as Node).id : end) as number

function useSize() {
  const [element, setElement] = useState<HTMLDivElement | null>(null)
  const [box, setBox] = useState({ width: 0, height: 0 })
  useEffect(() => {
    if (!element) return
    const observer = new ResizeObserver(([entry]) =>
      setBox({ width: entry.contentRect.width, height: entry.contentRect.height }),
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [element])
  return [setElement, box] as const
}

export function CourseMapPage() {
  const id = Number(useParams().id)
  const graph = useQuery({ queryKey: ['graph', id], queryFn: () => api<Graph>(`/courses/${id}/graph`) })
  const [selected, setSelected] = useState<number | null>(null)
  const [canvas, box] = useSize()
  const fg = useRef<Methods>(undefined)
  const fitted = useRef(false)

  const data = useMemo(
    () => ({
      nodes: (graph.data?.nodes ?? []).map((node) => ({ ...node })) as Node[],
      links: (graph.data?.edges ?? []).map((edge) => ({ ...edge })),
    }),
    [graph.data],
  )
  const names = useMemo(() => new Map(data.nodes.map((n) => [n.id as number, n.name])), [data])
  const edges = graph.data?.edges ?? []
  const lit = useMemo(() => (selected === null ? null : neighbours(selected, edges)), [selected, edges])

  const focus = useCallback(
    (conceptId: number) => {
      setSelected(conceptId)
      const node = data.nodes.find((n) => n.id === conceptId)
      if (!node || node.x === undefined) return
      const ratio = 1 + 90 / (Math.hypot(node.x, node.y ?? 0, node.z ?? 0) || 1)
      fg.current?.cameraPosition(
        { x: node.x * ratio, y: (node.y ?? 0) * ratio, z: (node.z ?? 0) * ratio },
        { x: node.x, y: node.y ?? 0, z: node.z ?? 0 },
        800,
      )
    },
    [data],
  )

  const label = useCallback(
    (node: Node) => {
      const sprite = new SpriteText(node.name, 5.5, !lit || lit.has(node.id as number) ? LABEL : LABEL_FADED)
      sprite.fontFace = 'Atkinson Hyperlegible, system-ui, sans-serif'
      sprite.position.set(0, radius(node) + 4, 0)
      return sprite
    },
    [lit],
  )

  const touches = (link: { source?: unknown; target?: unknown }) =>
    selected !== null && (endId(link.source) === selected || endId(link.target) === selected)

  if (graph.isPending) return <p className="page-note">Opening the concept map…</p>
  if (graph.isError) return <p className="page-note" role="alert">{graph.error.message}</p>

  const course = graph.data
  const current = course.nodes.find((n) => n.id === selected)
  return (
    <main className="map">
      <div className="deck-bar">
        <nav className="crumbs" aria-label="Breadcrumb">
          <Link to={`/courses/${course.course_id}`}>{course.course_title}</Link>
          <span aria-hidden="true">/</span>
          <h1>Concept map</h1>
        </nav>
      </div>
      <div className="map-body">
        <div className="map-canvas" ref={canvas}>
          {course.nodes.length === 0 ? (
            <p className="map-empty">No concepts yet. The map fills in as lessons are published.</p>
          ) : (
            box.width > 0 && (
              <ForceGraph3D<GraphNode>
                ref={fg}
                width={box.width}
                height={box.height}
                graphData={data}
                backgroundColor="#16243a"
                showNavInfo={false}
                nodeVal={size}
                nodeLabel={() => ''}
                nodeColor={(n) =>
                  n.id === selected ? '#ffe84d' : !lit || lit.has(n.id as number) ? '#7fa7dc' : FADED
                }
                nodeOpacity={0.95}
                nodeThreeObject={label}
                nodeThreeObjectExtend
                linkColor={(l) =>
                  selected === null || touches(l) ? (EDGE_TYPES[l.type]?.color ?? '#8a99ad') : FADED
                }
                linkWidth={(l) => (touches(l) ? 1.6 : 0.6)}
                linkOpacity={0.85}
                linkDirectionalArrowLength={3.5}
                linkDirectionalArrowRelPos={1}
                onNodeClick={(n) => focus(n.id as number)}
                onBackgroundClick={() => setSelected(null)}
                cooldownTime={4000}
                onEngineStop={() => {
                  if (fitted.current) return
                  fitted.current = true
                  fg.current?.zoomToFit(600, 40)
                }}
              />
            )
          )}
          <p className="map-hint">Drag to turn · scroll to zoom · tap a concept</p>
          {course.edges.length > 0 && (
            <ul className="map-legend" aria-label="Link colours">
              {Object.entries(EDGE_TYPES).map(([type, { color, legend }]) => (
                <li key={type}>
                  <span className="swatch" style={{ background: color }} />
                  {legend}
                </li>
              ))}
            </ul>
          )}
        </div>
        <aside className="map-panel" aria-live="polite">
          {current ? (
            <ConceptDetail node={current} related={relations(current.id, edges, names)} onPick={focus} />
          ) : (
            <div className="map-intro">
              <h2>
                {course.nodes.length} concepts, {course.edges.length}{' '}
                {course.edges.length === 1 ? 'link' : 'links'}
              </h2>
              <p>
                Each ball is a concept taught in this course; bigger ones come up more often. Arrows
                show how they depend on each other. Tap one to see what it needs, what it connects to,
                and the moments it was taught.
              </p>
            </div>
          )}
        </aside>
      </div>
    </main>
  )
}

function ConceptDetail({
  node,
  related,
  onPick,
}: {
  node: GraphNode
  related: ReturnType<typeof relations>
  onPick: (id: number) => void
}) {
  return (
    <article>
      <h2 className="map-title">{node.name}</h2>
      {node.aliases.length > 0 && <p className="map-aliases">Also called {node.aliases.join(', ')}</p>}
      {node.summary && <p className="map-summary">{node.summary}</p>}
      {related.map((group) => (
        <section key={group.label} className="map-group">
          <h3>{group.label}</h3>
          <ul className="map-chips">
            {group.concepts.map((c) => (
              <li key={c.id}>
                <button type="button" className="quiet" onClick={() => onPick(c.id)}>
                  {c.name}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
      <section className="map-group">
        <h3>Taught at</h3>
        <ol className="map-moments">
          {node.moments.map((m, index) => (
            <li key={index}>
              <Link to={`/lessons/${m.lesson_id}?t=${m.start_ms}`}>
                Lesson {m.lesson_position} · {m.lesson_title} · {clock(m.start_ms)}
              </Link>
              <p>{m.text}</p>
            </li>
          ))}
        </ol>
      </section>
    </article>
  )
}
