export function filterWatchlistItems(items = [], { query = '', market = 'all', recommendation = 'all' } = {}) {
  const q = query.trim().toLowerCase()
  return items.filter((item) => {
    const haystack = [item.symbol, item.name, item.industry, item.market]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    const matchesQuery = !q || haystack.includes(q)
    const matchesMarket = market === 'all' || item.market === market
    const rec = item.latest_signal?.recommendation || '无信号'
    const matchesRecommendation = recommendation === 'all' || rec === recommendation
    return matchesQuery && matchesMarket && matchesRecommendation
  })
}
