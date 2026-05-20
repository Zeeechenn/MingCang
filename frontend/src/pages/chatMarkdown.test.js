import assert from 'node:assert/strict'
import test from 'node:test'

import { parseChatMarkdown } from './chatMarkdown.js'

test('parseChatMarkdown keeps code blocks and lists separate', () => {
  const blocks = parseChatMarkdown(`# 标题

- A
- B

\`\`\`js
const x = 1
\`\`\`

正文`)

  assert.deepEqual(blocks.map((block) => block.type), ['h1', 'ul', 'code', 'p'])
  assert.equal(blocks[2].language, 'js')
  assert.equal(blocks[2].text.trim(), 'const x = 1')
})
