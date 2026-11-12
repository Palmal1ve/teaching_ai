import { describe, expect, it } from 'vitest'

import { neighbours, relations } from './relations'

const names = new Map([
  [1, 'Edge relaxation'],
  [2, 'Bellman-Ford'],
  [3, 'Dijkstra'],
  [4, 'Shortest path'],
])
const edges = [
  { source: 4, target: 2, type: 'PREREQUISITE_OF' },
  { source: 1, target: 2, type: 'PART_OF' },
  { source: 1, target: 3, type: 'PART_OF' },
  { source: 3, target: 2, type: 'CONTRASTS_WITH' },
  { source: 2, target: 3, type: 'CONTRASTS_WITH' },
]

describe('relations', () => {
  it('reads each edge from the point of view of the chosen concept', () => {
    expect(relations(2, edges, names)).toEqual([
      { label: 'Needs first', concepts: [{ id: 4, name: 'Shortest path' }] },
      { label: 'Made up of', concepts: [{ id: 1, name: 'Edge relaxation' }] },
      { label: 'Compared with', concepts: [{ id: 3, name: 'Dijkstra' }] },
    ])
  })

  it('groups and sorts concepts under one label', () => {
    expect(relations(1, edges, names)).toEqual([
      {
        label: 'Part of',
        concepts: [
          { id: 2, name: 'Bellman-Ford' },
          { id: 3, name: 'Dijkstra' },
        ],
      },
    ])
  })

  it('names an unknown edge type by its raw name', () => {
    expect(relations(1, [{ source: 1, target: 4, type: 'NEW_KIND' }], names)).toEqual([
      { label: 'NEW_KIND', concepts: [{ id: 4, name: 'Shortest path' }] },
    ])
  })
})

describe('neighbours', () => {
  it('includes the concept itself and everything one edge away', () => {
    expect([...neighbours(1, edges)].sort()).toEqual([1, 2, 3])
  })
})
