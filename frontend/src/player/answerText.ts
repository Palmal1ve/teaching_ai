const HEADING = /^[ \t]*(?:#+[ \t]*|\*\*)?Beyond the class material(?:\*\*)?:?[ \t]*$/im
const TRAILING_RULE = /(?:^|\n)[ \t]*-{3,}[ \t]*$/
const MARK = /\s\[(\d+)\]/g

type MdNode = { type: string; value?: string; url?: string; children?: MdNode[] }

export const citationHref = (n: number) => `#cite-${n}`

export function citationNumber(href: string | undefined): number | null {
  const match = /^#cite-(\d+)$/.exec(href ?? '')
  return match ? Number(match[1]) : null
}

export function splitBeyond(answer: string): { fromClass: string; beyond: string } {
  const match = HEADING.exec(answer)
  if (!match) return { fromClass: answer, beyond: '' }
  return {
    fromClass: answer.slice(0, match.index).trim().replace(TRAILING_RULE, '').trim(),
    beyond: answer.slice(match.index + match[0].length).trim(),
  }
}

function splitMarks(value: string, known: Set<number>): MdNode[] {
  const nodes: MdNode[] = []
  let from = 0
  for (const mark of value.matchAll(MARK)) {
    const n = Number(mark[1])
    if (!known.has(n)) continue
    if (mark.index > from) nodes.push({ type: 'text', value: value.slice(from, mark.index) + ' ' })
    nodes.push({ type: 'link', url: citationHref(n), children: [{ type: 'text', value: mark[1] }] })
    from = mark.index + mark[0].length
  }
  if (from < value.length) nodes.push({ type: 'text', value: value.slice(from) })
  return nodes
}

// Runs on text nodes only, so code spans and code blocks keep their [n].
export function citationMarks(numbers: number[]) {
  const known = new Set(numbers)
  const walk = (node: MdNode) => {
    if (!node.children) return
    node.children = node.children.flatMap((child) => {
      if (child.type === 'text') return splitMarks(child.value ?? '', known)
      walk(child)
      return [child]
    })
  }
  return walk
}
