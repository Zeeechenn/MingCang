function flushParagraph(blocks, paragraph) {
  if (paragraph.length) {
    blocks.push({ type: 'p', text: paragraph.join(' ') })
    paragraph.length = 0
  }
}

function flushList(blocks, list, type) {
  if (list.length) {
    blocks.push({ type, items: [...list] })
    list.length = 0
  }
}

export function parseChatMarkdown(markdown = '') {
  const blocks = []
  const paragraph = []
  const list = []
  let listType = 'ul'
  let code = null

  for (const line of String(markdown).split(/\r?\n/)) {
    const fence = /^```(\w+)?\s*$/.exec(line.trim())
    if (fence) {
      if (code) {
        blocks.push({ type: 'code', language: code.language, text: code.lines.join('\n') })
        code = null
      } else {
        flushParagraph(blocks, paragraph)
        flushList(blocks, list, listType)
        code = { language: fence[1] || '', lines: [] }
      }
      continue
    }
    if (code) {
      code.lines.push(line)
      continue
    }

    const trimmed = line.trim()
    if (!trimmed) {
      flushParagraph(blocks, paragraph)
      flushList(blocks, list, listType)
      listType = 'ul'
      continue
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(trimmed)
    if (heading) {
      flushParagraph(blocks, paragraph)
      flushList(blocks, list, listType)
      blocks.push({ type: `h${heading[1].length}`, text: heading[2] })
      continue
    }
    const bullet = /^[-*]\s+(.+)$/.exec(trimmed)
    if (bullet) {
      flushParagraph(blocks, paragraph)
      if (list.length && listType !== 'ul') flushList(blocks, list, listType)
      listType = 'ul'
      list.push(bullet[1])
      continue
    }
    const ordered = /^\d+\.\s+(.+)$/.exec(trimmed)
    if (ordered) {
      flushParagraph(blocks, paragraph)
      if (list.length && listType !== 'ol') flushList(blocks, list, listType)
      listType = 'ol'
      list.push(ordered[1])
      continue
    }
    flushList(blocks, list, listType)
    paragraph.push(trimmed)
  }

  if (code) blocks.push({ type: 'code', language: code.language, text: code.lines.join('\n') })
  flushParagraph(blocks, paragraph)
  flushList(blocks, list, listType)
  return blocks
}
