import { describe, expect, it } from 'vitest'

import { type Item, LAYOUTS, leaves, parseChoice, withoutSlides } from './layouts'

const sizesSum = (items: Item[]) => items.reduce((sum, item) => sum + item.size, 0)

describe('withoutSlides', () => {
  it.each(LAYOUTS)('drops the slides panel from $name and keeps sizes at 100', (layout) => {
    const pruned = withoutSlides(layout.root)
    expect(leaves(pruned)).not.toContain('slides')
    expect(leaves(pruned)).toContain('video')
    const check = (item: Item) => {
      if ('panel' in item) return
      expect(sizesSum(item.items)).toBeCloseTo(100)
      item.items.forEach(check)
    }
    check(pruned)
  })
})

describe('parseChoice', () => {
  it('defaults to Classic and asking at start', () => {
    expect(parseChoice(null)).toEqual({ layout: 'classic', askAtStart: true })
  })

  it('reads a saved choice', () => {
    expect(parseChoice('{"layout":"grid","askAtStart":false}')).toEqual({ layout: 'grid', askAtStart: false })
  })

  it.each(['not json', 'null', '{"layout":"nope"}'])('falls back on a bad value: %s', (raw) => {
    expect(parseChoice(raw)).toEqual({ layout: 'classic', askAtStart: true })
  })
})
