const EMPTY = '-'

function toFiniteNumber(value) {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function fixed(value, digits) {
  const out = value.toFixed(digits)
  return out.startsWith('-0') ? out.slice(1) : out
}

export function formatNumber(value, options = {}) {
  const n = toFiniteNumber(value)
  if (n === null) return EMPTY
  return n.toLocaleString('zh-CN', {
    maximumFractionDigits: options.maximumFractionDigits ?? 2,
    minimumFractionDigits: options.minimumFractionDigits ?? 0,
  })
}

export function formatPrice(value) {
  return formatNumber(value, { maximumFractionDigits: 2, minimumFractionDigits: 2 })
}

export function formatMoney(value) {
  return formatNumber(value, { maximumFractionDigits: 2 })
}

export function formatPositionSize(value) {
  return formatNumber(value, { maximumFractionDigits: 4 })
}

export function formatSignedMoney(value) {
  const n = toFiniteNumber(value)
  if (n === null) return EMPTY
  return `${n > 0 ? '+' : ''}${formatMoney(n)}`
}

export function formatSignedNumber(value, digits = 1) {
  const n = toFiniteNumber(value)
  if (n === null) return EMPTY
  const text = fixed(n, digits)
  return `${n > 0 ? '+' : ''}${text}`
}

export function formatSignedPercent(value) {
  const n = toFiniteNumber(value)
  if (n === null) return EMPTY
  const text = fixed(n, 2)
  return `${n > 0 ? '+' : ''}${text}%`
}

export function formatPositionPercent(value) {
  const n = toFiniteNumber(value)
  if (n === null) return EMPTY
  return `${fixed(n * 100, 1)}%`
}

export function formatScore(value, digits = 1) {
  const n = toFiniteNumber(value)
  if (n === null) return EMPTY
  return fixed(n, digits)
}

export function formatDate(value) {
  if (value === null || value === undefined || value === '') return EMPTY
  const text = String(value)
  const match = text.match(/^(\d{4}-\d{2}-\d{2})/)
  return match ? match[1] : text
}

export function formatAdjustment(value) {
  if (value === null || value === undefined || value === '') return '未标注'
  const key = String(value).toLowerCase()
  if (key === 'qfq') return '前复权(qfq)'
  if (key === 'hfq') return '后复权(hfq)'
  if (key === 'forward_additive') return '前向补齐'
  return String(value)
}

export function formatPriceWithAdjustment(value, adjustment) {
  return `${formatPrice(value)} ${formatAdjustment(adjustment)}`
}
