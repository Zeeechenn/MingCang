export const SECONDARY_SECTIONS = [
  'dossier',
  'news',
  'evidence',
  'research',
  'coverage',
  'longTerm',
  'history',
]

export function createSecondaryLoadingStatus() {
  return Object.fromEntries(
    SECONDARY_SECTIONS.map((name) => [name, { loading: true, error: '' }]),
  )
}

export function markStockDetailSection(status, name, patch) {
  return {
    ...status,
    [name]: {
      ...(status[name] || { loading: false, error: '' }),
      ...patch,
    },
  }
}

export function hasSecondaryLoading(status) {
  return SECONDARY_SECTIONS.some((name) => Boolean(status[name]?.loading))
}
