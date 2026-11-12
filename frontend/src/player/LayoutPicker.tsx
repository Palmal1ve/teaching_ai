import { useEffect, useRef } from 'react'

import { type Item, isFoldable, LAYOUTS, type LayoutId, leaves, withoutSlides } from './layouts'

const LABELS = { video: 'Video', transcript: 'Transcript', slides: 'Slides', chat: 'Ask' }

function Sketch({ item, solo }: { item: Item; solo?: boolean }) {
  if ('panel' in item) {
    return (
      <span className={`sketch-cell sketch-${item.panel}`} style={{ flexGrow: item.size }}>
        {LABELS[item.panel]}
      </span>
    )
  }
  const items = solo ? item.items.filter((child) => leaves(child).some((panel) => !isFoldable(panel))) : item.items
  return (
    <span className={`sketch-split ${item.split}`} style={{ flexGrow: item.size }}>
      {items.map((child) => (
        <Sketch key={leaves(child).join('-')} item={child} solo={solo} />
      ))}
    </span>
  )
}

export function LayoutPicker({
  open,
  current,
  hasSlides,
  askAtStart,
  onAskAtStart,
  onPick,
  onClose,
}: {
  open: boolean
  current: LayoutId
  hasSlides: boolean
  askAtStart: boolean
  onAskAtStart: (ask: boolean) => void
  onPick: (layout: LayoutId) => void
  onClose: () => void
}) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog ref={ref} className="layout-picker" aria-labelledby="layout-title" onClose={onClose}>
      <h2 id="layout-title">Choose a layout</h2>
      <p>You can change it any time with the Layout button at the top right.</p>
      <div className="layout-options">
        {LAYOUTS.map((layout) => (
          <button
            key={layout.id}
            type="button"
            aria-pressed={layout.id === current}
            onClick={() => onPick(layout.id)}
          >
            <span className="sketch" aria-hidden="true">
              <Sketch item={hasSlides ? layout.root : withoutSlides(layout.root)} solo={layout.solo} />
            </span>
            <strong>{layout.name}</strong>
            <span>{layout.hint}</span>
          </button>
        ))}
      </div>
      <footer>
        <label>
          <input type="checkbox" checked={askAtStart} onChange={(event) => onAskAtStart(event.target.checked)} />
          Show this when a lesson opens
        </label>
        <button type="button" className="quiet" onClick={onClose}>
          Keep current
        </button>
      </footer>
    </dialog>
  )
}
