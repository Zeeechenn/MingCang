import assert from 'node:assert/strict'
import test from 'node:test'

import { buildReviewHistory, parseMarkdownBlocks } from './reviewContent.js'

test('parseMarkdownBlocks renders headings, lists, tables, and paragraphs', () => {
  const blocks = parseMarkdownBlocks(`# 标题

## 摘要
- 信号：6 条
- 安全审计：pass

1. 控制仓位
2. 等待确认

| 股票 | 综合分 |
|---|---:|
| 300308 中际旭创 | +36.0 |

普通段落`)

  assert.deepEqual(
    blocks.map((block) => block.type),
    ['h1', 'h2', 'ul', 'ol', 'table', 'p'],
  )
  assert.equal(blocks[2].items.length, 2)
  assert.equal(blocks[3].items[0], '控制仓位')
  assert.equal(blocks[4].rows[0][0], '300308 中际旭创')
})

test('buildReviewHistory keeps real rows first and fills demo rows to show history', () => {
  const real = [{ id: 'real-1', kind: 'daily', as_of: '2026-05-19', summary: '真实复盘' }]
  const demos = [
    { id: 'demo-1', kind: 'daily', as_of: '2026-05-18', summary: '示例 1', demo: true },
    { id: 'demo-2', kind: 'long_term', as_of: '2026-W20', summary: '示例 2', demo: true },
  ]

  const history = buildReviewHistory(real, demos, 3)

  assert.equal(history.length, 3)
  assert.equal(history[0].id, 'real-1')
  assert.equal(history[1].id, 'demo-1')
  assert.equal(history[2].id, 'demo-2')
})
