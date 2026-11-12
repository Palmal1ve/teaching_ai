import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { AnswerMarkdown } from './AnswerMarkdown'
import { splitBeyond } from './answerText'

const render = (text: string, citations: number[] = [1]) =>
  renderToStaticMarkup(
    createElement(AnswerMarkdown, {
      text,
      citations,
      chip: (n: number) => createElement('button', null, `chip ${n}`),
    }),
  )

describe('splitBeyond', () => {
  it('separates the class answer from general knowledge', () => {
    const result = splitBeyond('From class. [1]\n\n## Beyond the class material\nGeneral.')
    expect(result).toEqual({ fromClass: 'From class. [1]', beyond: 'General.' })
  })
  it('accepts a bold heading', () => {
    expect(splitBeyond('A\n**Beyond the class material**\nB').beyond).toBe('B')
  })
  it('leaves an answer with no such section alone', () => {
    expect(splitBeyond('Just class.')).toEqual({ fromClass: 'Just class.', beyond: '' })
  })
  it('removes a rule left before the Beyond heading', () => {
    const result = splitBeyond('From class. [1]\n\n---\n\n## Beyond the class material\nGeneral.')
    expect(result.fromClass).toBe('From class. [1]')
  })
  it('keeps a rule in the middle of the class answer', () => {
    const result = splitBeyond('One.\n\n---\n\nTwo.\n\n## Beyond the class material\nGeneral.')
    expect(result.fromClass).toBe('One.\n\n---\n\nTwo.')
  })
})

describe('AnswerMarkdown', () => {
  it('renders headings', () => {
    expect(render('## Why it fails')).toContain('<h2>Why it fails</h2>')
  })
  it('renders bold text', () => {
    expect(render('A **greedy** choice')).toContain('<strong>greedy</strong>')
  })
  it('renders lists with their chips', () => {
    const html = render('- One. [1]\n- Two.')
    expect(html).toContain('<ul>')
    expect(html).toContain('<li>One. <button>chip 1</button></li>')
  })
  it('renders a table with chips in its cells', () => {
    const html = render('| Name | Note |\n|---|---|\n| Dijkstra | Greedy. [1] |')
    expect(html).toContain('<table>')
    expect(html).toContain('Greedy. <button>chip 1</button>')
  })
  it('turns several marks on one sentence into chips', () => {
    const html = render('Claim. [1] [2]', [1, 2])
    expect(html).toContain('<button>chip 1</button><button>chip 2</button>')
  })
  it('leaves [1] alone inside a code block', () => {
    const html = render('```python\nprint(dist [1])\n```')
    expect(html).toContain('dist [1]')
    expect(html).not.toContain('chip')
  })
  it('leaves [1] alone inside a code span', () => {
    const html = render('Use `dist [1]` here.')
    expect(html).toContain('<code>dist [1]</code>')
    expect(html).not.toContain('chip')
  })
  it('leaves array indexing in plain text alone', () => {
    const html = render('Set dist[1] to zero.')
    expect(html).toContain('dist[1]')
    expect(html).not.toContain('chip')
  })
  it('leaves a mark with no matching citation alone', () => {
    const html = render('The list [7] is short.')
    expect(html).toContain('The list [7] is short.')
    expect(html).not.toContain('chip')
  })
  it('does not load images from an answer', () => {
    expect(render('![x](http://example.com/a.png)')).not.toContain('<img')
  })
  it('does not render raw HTML from an answer', () => {
    expect(render('<script>alert(1)</script>')).not.toContain('<script')
  })
})
