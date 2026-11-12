export type Edge = { source: number; target: number; type: string }
export type Related = { label: string; concepts: { id: number; name: string }[] }

export const EDGE_TYPES: Record<string, { color: string; legend: string; out: string; in: string }> = {
  PREREQUISITE_OF: { color: '#bf2f1c', legend: 'Needed before', out: 'Unlocks', in: 'Needs first' },
  PART_OF: { color: '#2c5a9a', legend: 'Part of', out: 'Part of', in: 'Made up of' },
  IS_A: { color: '#6a4c93', legend: 'A kind of', out: 'A kind of', in: 'Kinds' },
  USED_FOR: { color: '#22703f', legend: 'Used for', out: 'Used for', in: 'Uses' },
  CONTRASTS_WITH: { color: '#b86e00', legend: 'Compared with', out: 'Compared with', in: 'Compared with' },
  RELATED_TO: { color: '#8a99ad', legend: 'Related to', out: 'Related to', in: 'Related to' },
}

const ORDER = Object.values(EDGE_TYPES).flatMap((t) => [t.in, t.out])

export function relations(id: number, edges: Edge[], names: Map<number, string>): Related[] {
  const groups = new Map<string, Map<number, string>>()
  for (const edge of edges) {
    const outgoing = edge.source === id
    if (!outgoing && edge.target !== id) continue
    const other = outgoing ? edge.target : edge.source
    const type = EDGE_TYPES[edge.type]
    const label = type ? (outgoing ? type.out : type.in) : edge.type
    if (!groups.has(label)) groups.set(label, new Map())
    groups.get(label)!.set(other, names.get(other) ?? '')
  }
  const rank = (label: string) => (ORDER.includes(label) ? ORDER.indexOf(label) : ORDER.length)
  return [...groups]
    .sort(([a], [b]) => rank(a) - rank(b))
    .map(([label, concepts]) => ({
      label,
      concepts: [...concepts]
        .map(([cid, name]) => ({ id: cid, name }))
        .sort((a, b) => a.name.localeCompare(b.name)),
    }))
}

export function neighbours(id: number, edges: Edge[]): Set<number> {
  const result = new Set([id])
  for (const edge of edges) {
    if (edge.source === id) result.add(edge.target)
    if (edge.target === id) result.add(edge.source)
  }
  return result
}
