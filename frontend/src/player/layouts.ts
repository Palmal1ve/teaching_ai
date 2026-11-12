export type PanelId = 'video' | 'transcript' | 'slides' | 'chat'
export type FoldableId = 'transcript' | 'chat'
export type Leaf = { panel: PanelId; size: number }
export type Split = { split: 'horizontal' | 'vertical'; size: number; items: Item[] }
export type Item = Leaf | Split
export type LayoutId = 'classic' | 'slides' | 'video' | 'grid' | 'theater'
export type Layout = { id: LayoutId; name: string; hint: string; root: Split; solo?: boolean }
export type Choice = { layout: LayoutId; askAtStart: boolean }

const leaf = (panel: PanelId, size: number): Leaf => ({ panel, size })
const row = (size: number, ...items: Item[]): Split => ({ split: 'horizontal', size, items })
const column = (size: number, ...items: Item[]): Split => ({ split: 'vertical', size, items })

export const LAYOUTS: Layout[] = [
  {
    id: 'classic',
    name: 'Classic',
    hint: 'Video over transcript, slides, chat',
    root: row(100, column(38, leaf('video', 50), leaf('transcript', 50)), leaf('slides', 36), leaf('chat', 26)),
  },
  {
    id: 'slides',
    name: 'Slides focus',
    hint: 'Large slides, small video',
    root: row(100, column(26, leaf('video', 40), leaf('transcript', 60)), leaf('slides', 50), leaf('chat', 24)),
  },
  {
    id: 'video',
    name: 'Video focus',
    hint: 'Large video, slides and transcript beside it',
    root: row(100, leaf('video', 50), column(28, leaf('slides', 50), leaf('transcript', 50)), leaf('chat', 22)),
  },
  {
    id: 'grid',
    name: 'Grid',
    hint: 'Video and slides on top, transcript and chat below',
    root: column(100, row(55, leaf('video', 50), leaf('slides', 50)), row(45, leaf('transcript', 50), leaf('chat', 50))),
  },
  {
    id: 'theater',
    name: 'Theater',
    hint: 'Video only. Turn Transcript or Ask back on from the top bar',
    root: row(100, column(74, leaf('video', 75), leaf('transcript', 25)), leaf('chat', 26)),
    solo: true,
  },
]

export const findLayout = (id: LayoutId) => LAYOUTS.find((layout) => layout.id === id) ?? LAYOUTS[0]

export const isFoldable = (panel: PanelId): panel is FoldableId => panel === 'transcript' || panel === 'chat'

export const leaves = (item: Item): PanelId[] => ('panel' in item ? [item.panel] : item.items.flatMap(leaves))

export function withoutSlides(split: Split): Split {
  const items = split.items
    .filter((item) => !('panel' in item && item.panel === 'slides'))
    .map((item) => ('panel' in item ? item : withoutSlides(item)))
  const total = items.reduce((sum, item) => sum + item.size, 0)
  return { ...split, items: items.map((item) => ({ ...item, size: (item.size * 100) / total })) }
}

const CHOICE_KEY = 'player-layout'

export function parseChoice(raw: string | null): Choice {
  try {
    const saved = JSON.parse(raw ?? '{}')
    return {
      layout: LAYOUTS.some((layout) => layout.id === saved.layout) ? saved.layout : 'classic',
      askAtStart: saved.askAtStart !== false,
    }
  } catch {
    return { layout: 'classic', askAtStart: true }
  }
}

export function readChoice(): Choice {
  try {
    return parseChoice(localStorage.getItem(CHOICE_KEY))
  } catch {
    return parseChoice(null)
  }
}

export function saveChoice(choice: Choice) {
  try {
    localStorage.setItem(CHOICE_KEY, JSON.stringify(choice))
  } catch {
    // Storage can be refused; the layout still holds for this visit.
  }
}
