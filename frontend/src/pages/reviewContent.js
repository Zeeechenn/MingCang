function isTableDivider(line) {
  return /^\s*\|?[\s:-]+\|[\s|:-]*\s*$/.test(line)
}

function splitTableRow(line) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

function flushParagraph(blocks, paragraph) {
  if (paragraph.length) {
    blocks.push({ type: 'p', text: paragraph.join(' ') })
    paragraph.length = 0
  }
}

function flushList(blocks, list, type = 'ul') {
  if (list.length) {
    blocks.push({ type, items: [...list] })
    list.length = 0
  }
}

export function parseMarkdownBlocks(markdown = '') {
  const blocks = []
  const paragraph = []
  const list = []
  let listType = 'ul'
  const lines = String(markdown).split(/\r?\n/)

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i]
    const trimmed = line.trim()

    if (!trimmed) {
      flushParagraph(blocks, paragraph)
      flushList(blocks, list, listType)
      listType = 'ul'
      continue
    }

    if (trimmed.startsWith('|') && lines[i + 1] && isTableDivider(lines[i + 1])) {
      flushParagraph(blocks, paragraph)
      flushList(blocks, list, listType)
      listType = 'ul'
      const headers = splitTableRow(trimmed)
      i += 2
      const rows = []
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        rows.push(splitTableRow(lines[i]))
        i += 1
      }
      i -= 1
      blocks.push({ type: 'table', headers, rows })
      continue
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(trimmed)
    if (heading) {
      flushParagraph(blocks, paragraph)
      flushList(blocks, list, listType)
      listType = 'ul'
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
    listType = 'ul'
    paragraph.push(trimmed)
  }

  flushParagraph(blocks, paragraph)
  flushList(blocks, list, listType)
  return blocks
}

export function buildReviewHistory(rows = [], demos = [], minimum = 8) {
  const seen = new Set()
  const merged = []

  for (const item of [...rows, ...demos]) {
    if (!item?.id || seen.has(item.id)) continue
    seen.add(item.id)
    merged.push(item)
  }

  return merged.slice(0, Math.max(minimum, rows.length))
}
