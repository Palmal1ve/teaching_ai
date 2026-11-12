import type { ReactNode } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { citationMarks, citationNumber } from './answerText'

type Props = {
  text: string
  citations?: number[]
  chip?: (n: number) => ReactNode
}

export function AnswerMarkdown({ text, citations = [], chip }: Props) {
  return (
    <div className="answer-body">
      <Markdown
        remarkPlugins={[remarkGfm, [citationMarks, citations]]}
        disallowedElements={['img']}
        unwrapDisallowed
        components={{
          a: ({ href, children }) => {
            const n = citationNumber(href)
            if (n !== null && citations.includes(n)) return chip?.(n)
            return (
              <a href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            )
          },
        }}
      >
        {text}
      </Markdown>
    </div>
  )
}
