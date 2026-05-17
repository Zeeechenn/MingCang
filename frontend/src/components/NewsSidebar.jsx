function SentimentBar({ score }) {
  if (score == null) return null
  const pct = ((score + 1) / 2) * 100
  const color = score > 0.2 ? '#ef4444' : score < -0.2 ? '#22c55e' : '#eab308'
  return (
    <div className="mt-1 flex items-center gap-1.5">
      <div className="flex-1 bg-gray-700 rounded-full h-1">
        <div className="h-1 rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="text-xs font-mono w-8 text-right" style={{ color }}>
        {score > 0 ? '+' : ''}{score.toFixed(2)}
      </span>
    </div>
  )
}

function normalizeUrl(url) {
  if (!url) return ''
  if (url.startsWith('http://')) return `https://${url.slice('http://'.length)}`
  return url
}

function openNews(url) {
  const safeUrl = normalizeUrl(url)
  if (!safeUrl) return
  window.open(safeUrl, '_blank', 'noopener,noreferrer')
}

export default function NewsSidebar({ news }) {
  if (!news) {
    return (
      <div className="rounded-sm border border-stone-300 bg-[#faf6ec] p-4 text-center text-sm text-stone-500 dark:border-slate-700 dark:bg-[#1d232e] dark:text-slate-500">
        加载中…
      </div>
    )
  }
  if (news.length === 0) {
    return (
      <div className="rounded-sm border border-stone-300 bg-[#faf6ec] p-4 text-center text-sm text-stone-500 dark:border-slate-700 dark:bg-[#1d232e] dark:text-slate-500">
        近期无相关新闻
      </div>
    )
  }

  return (
    <div className="rounded-sm border border-stone-300 bg-[#faf6ec] p-4 dark:border-slate-700 dark:bg-[#1d232e]">
      <div className="mb-3 text-sm font-medium text-stone-950 dark:text-slate-300">近期新闻</div>
      <ul className="space-y-3 max-h-[calc(100vh-20rem)] overflow-y-auto pr-1">
        {news.map(item => (
          <li key={item.id} className="border-b border-stone-300 pb-3 last:border-0 last:pb-0 dark:border-slate-700">
            <button
              type="button"
              onClick={() => openNews(item.url)}
              className="block w-full text-left text-sm leading-snug text-stone-950 transition-colors hover:text-cyan-700 disabled:cursor-not-allowed disabled:text-stone-400 dark:text-slate-200 dark:hover:text-cyan-300 dark:disabled:text-slate-600"
              disabled={!item.url}
            >
              {item.title}
            </button>
            <div className="mt-1 flex items-center justify-between gap-2">
              <div className="min-w-0">
                <span className="text-xs text-stone-500 dark:text-slate-500">{item.source}</span>
                <span className="ml-2 text-xs text-stone-400 dark:text-slate-600">{item.published_at}</span>
              </div>
              {item.url && (
                <button
                  type="button"
                  onClick={() => openNews(item.url)}
                  className="shrink-0 rounded-sm border border-stone-300 bg-[#f3eddc] px-2 py-0.5 text-[10px] text-stone-600 hover:border-cyan-700 hover:text-cyan-700 dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-500 dark:hover:border-cyan-400 dark:hover:text-cyan-300"
                >
                  打开
                </button>
              )}
            </div>
            <SentimentBar score={item.sentiment_score} />
          </li>
        ))}
      </ul>
    </div>
  )
}
