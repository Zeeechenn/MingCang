import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { getDashboardSummary, getWatchlist, addStock, removeStock, searchStocks } from '../api'
import {
  formatDate,
  formatMoney,
  formatPrice,
  formatSignedNumber,
  formatSignedPercent,
} from '../financialNumbers'
import { filterWatchlistItems } from './watchlistFilters'
import { APP_VERSION } from '../version'

const REC_STYLE = {
  可小仓试错: 'border-red-500/35 bg-red-500/10 text-red-700 dark:text-red-200',
  可关注: 'border-red-500/25 bg-red-500/10 text-red-700 dark:text-red-200',
  买入: 'border-red-500/35 bg-red-500/10 text-red-700 dark:text-red-200',
  强买: 'border-red-600/40 bg-red-600/20 text-red-700 dark:text-red-100',
  观望: 'border-amber-500/35 bg-amber-500/10 text-amber-700 dark:text-amber-200',
  规避: 'border-emerald-500/35 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200',
  卖出: 'border-emerald-500/35 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200',
  强卖: 'border-emerald-600/40 bg-emerald-600/20 text-emerald-700 dark:text-emerald-100',
}

const PANEL = 'rounded-sm border border-stone-300/80 bg-[#faf6ec] dark:border-slate-700 dark:bg-[#1d232e]'
const PANEL_ALT = 'rounded-sm border border-stone-300/80 bg-[#fffaf0] dark:border-slate-700 dark:bg-[#222936]'
const LABEL = 'text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500 dark:text-slate-400'
const RELEASE_ITEMS = [
  [`v${APP_VERSION}`, '信任补丁'],
  ['Case-loop', '案例闭环架构'],
  ['M30', '多空证据账本'],
  ['Quant', '生产继续关闭'],
]

function recClass(rec) {
  return REC_STYLE[rec] || 'border-slate-400/40 bg-slate-500/10 text-slate-600 dark:text-slate-300'
}

function longTermClass(label) {
  if (label === '值得持有') return 'border-red-500/35 bg-red-500/10 text-red-700 dark:text-red-200'
  if (label === '估值偏高') return 'border-amber-500/35 bg-amber-500/10 text-amber-700 dark:text-amber-200'
  if (label === '规避') return 'border-emerald-500/35 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200'
  return 'border-cyan-600/30 bg-cyan-600/10 text-cyan-700 dark:text-cyan-200'
}

function getBullBear(signal) {
  const arb = signal?.llm_arbitration || {}
  return {
    bull: arb.bull_points?.length ? arb.bull_points : ['等待下一次信号沉淀多方证据'],
    bear: arb.bear_points?.length ? arb.bear_points : ['等待下一次信号沉淀空方风险'],
    rationale: arb.rationale || '暂无裁决摘要，下一次 harness 记录会补充。',
    bias: arb.action_bias || '中性',
  }
}

function Section({ title, eyebrow, right, children }) {
  return (
    <section className={PANEL}>
      <div className="flex min-h-12 items-center justify-between border-b border-stone-300/80 px-4 dark:border-slate-700">
        <div>
          {eyebrow && <div className={LABEL}>{eyebrow}</div>}
          <h2 className="text-sm font-semibold text-stone-950 dark:text-slate-100">{title}</h2>
        </div>
        {right}
      </div>
      <div className="p-4">{children}</div>
    </section>
  )
}

function ReleaseStatus() {
  return (
    <div className={`${PANEL} p-4`}>
      <div className="grid gap-3 lg:grid-cols-[1fr_auto] lg:items-center">
        <div>
          <div className={LABEL}>当前发布</div>
          <div className="mt-1 text-sm font-medium text-stone-950 dark:text-slate-100">
            v{APP_VERSION} 案例闭环架构落地，多空证据账本持续沉淀，量化生产待下一轮评审开放。
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {RELEASE_ITEMS.map(([label, value]) => (
            <div key={label} className="rounded-sm border border-stone-300 bg-[#f3eddc] px-3 py-2 dark:border-slate-700 dark:bg-[#161b25]">
              <div className="font-mono text-[11px] font-semibold text-cyan-700 dark:text-cyan-200">{label}</div>
              <div className="mt-1 text-xs text-stone-600 dark:text-slate-300">{value}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function ScoreArc({ score }) {
  const clamped = Math.max(-100, Math.min(100, Number(score || 0)))
  const color = clamped > 20 ? 'bg-red-500' : clamped < -20 ? 'bg-emerald-500' : 'bg-amber-500'
  const width = `${Math.abs(clamped) / 2}%`
  const left = clamped < 0 ? `${50 - Math.abs(clamped) / 2}%` : '50%'
  return (
    <div>
      <div className="flex items-end justify-between">
        <div>
          <div className={LABEL}>综合评分</div>
          <div className="mt-1 font-mono text-6xl font-semibold tracking-tight text-stone-950 dark:text-slate-50">
            {formatSignedNumber(clamped, 1)}
          </div>
        </div>
        <div className="pb-2 text-right">
          <div className="text-xs text-stone-500 dark:text-slate-400">区间 -100 / +100</div>
          <div className="mt-1 text-xs text-stone-500 dark:text-slate-400">红=偏多，绿=偏空</div>
        </div>
      </div>
      <div className="relative mt-4 h-2 rounded-full bg-stone-300 dark:bg-slate-800">
        <div className={`absolute top-0 h-2 rounded-full ${color}`} style={{ left, width }} />
        <div className="absolute left-1/2 top-[-4px] h-4 w-px bg-stone-500 dark:bg-slate-500" />
      </div>
    </div>
  )
}

function TodayCall({ summary, watchlist }) {
  const signal = summary?.signals?.latest?.[0] || watchlist.find((item) => item.latest_signal)?.latest_signal
  const stock = watchlist.find((item) => item.symbol === signal?.symbol) || {}
  const debate = getBullBear(signal)
  return (
    <section className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
      <div className={PANEL_ALT}>
        <div className="border-b border-stone-300/80 p-5 dark:border-slate-700">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className={LABEL}>今日决策</div>
              <div className="mt-3 flex flex-wrap items-baseline gap-3">
                <h1 className="text-4xl font-semibold tracking-tight text-stone-950 dark:text-slate-50">
                  {stock.name || signal?.symbol || '暂无信号'}
                </h1>
                <span className="font-mono text-sm text-stone-500 dark:text-slate-400">{signal?.symbol || '-'}</span>
                {signal?.recommendation && (
                  <span className={`rounded-sm border px-2.5 py-1 text-xs font-semibold ${recClass(signal.recommendation)}`}>
                    {signal.recommendation}
                  </span>
                )}
                {stock.long_term_label?.label && (
                  <span className={`rounded-sm border px-2.5 py-1 text-xs font-semibold ${longTermClass(stock.long_term_label.label)}`}>
                    长期 {stock.long_term_label.label}
                  </span>
                )}
              </div>
              <p className="mt-2 text-sm text-stone-600 dark:text-slate-300">
                {stock.industry || '未标注行业'} · 当前规则 {summary?.system?.profile || '未加载'} · 阈值 {summary?.system?.entry_threshold ?? '-'}
              </p>
            </div>
            <div className="text-right">
              <div className={LABEL}>信号日期</div>
              <div className="mt-2 font-mono text-sm text-stone-700 dark:text-slate-200">{formatDate(signal?.date)}</div>
            </div>
          </div>
        </div>

        <div className="grid gap-5 p-5 md:grid-cols-[0.8fr_1fr]">
          <ScoreArc score={signal?.composite_score} />
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-2">
              <Metric label="量化" value={formatSignedNumber(signal?.quant_score, 1)} tone="cyan" />
              <Metric label="技术" value={formatSignedNumber(signal?.technical_score, 1)} tone="cyan" />
              <Metric label="情感" value={formatSignedNumber(signal?.sentiment_score, 2)} tone="amber" />
            </div>
            <div className="grid grid-cols-3 gap-2">
              <Metric label="止损" value={formatPrice(signal?.stop_loss)} tone="green" />
              <Metric label="止盈" value={formatPrice(signal?.take_profit)} tone="red" />
              <Metric label="置信度" value={signal?.confidence || '-'} />
            </div>
            <blockquote className="border-l-2 border-cyan-600/70 pl-4 font-serif text-lg italic leading-relaxed text-stone-800 dark:text-slate-100">
              {debate.rationale}
            </blockquote>
          </div>
        </div>
      </div>

      <div className={PANEL_ALT}>
        <div className="flex items-center justify-between border-b border-stone-300/80 p-4 dark:border-slate-700">
          <div>
            <div className={LABEL}>多空辩论</div>
            <h2 className="text-sm font-semibold text-stone-950 dark:text-slate-100">系统裁决：{debate.bias}</h2>
          </div>
          <span className="rounded-sm border border-cyan-600/30 bg-cyan-600/10 px-2 py-1 text-xs text-cyan-700 dark:text-cyan-200">
            研究总监
          </span>
        </div>
        <div className="grid gap-0 md:grid-cols-2">
          <DebateColumn title="多方论点" items={debate.bull} tone="bull" />
          <DebateColumn title="空方风险" items={debate.bear} tone="bear" />
        </div>
      </div>
    </section>
  )
}

function Metric({ label, value, tone = 'neutral' }) {
  const toneClass = {
    neutral: 'text-stone-950 dark:text-slate-100',
    cyan: 'text-cyan-700 dark:text-cyan-200',
    red: 'text-red-700 dark:text-red-200',
    green: 'text-emerald-700 dark:text-emerald-200',
    amber: 'text-amber-700 dark:text-amber-200',
  }[tone]
  return (
    <div className="rounded-sm border border-stone-300 bg-[#f3eddc] p-3 dark:border-slate-700 dark:bg-[#161b25]">
      <div className={LABEL}>{label}</div>
      <div className={`mt-2 font-mono text-xl font-semibold ${toneClass}`}>{value}</div>
    </div>
  )
}

function DebateColumn({ title, items, tone }) {
  const bullish = tone === 'bull'
  return (
    <div className={`p-4 ${bullish ? '' : 'border-t border-stone-300 dark:border-slate-700 md:border-l md:border-t-0'}`}>
      <div className={`mb-3 text-xs font-semibold ${bullish ? 'text-red-700 dark:text-red-200' : 'text-emerald-700 dark:text-emerald-200'}`}>
        {title}
      </div>
      <ul className="space-y-2">
        {items.slice(0, 4).map((item, index) => (
          <li key={index} className="flex gap-2 text-sm leading-relaxed text-stone-700 dark:text-slate-300">
            <span className={bullish ? 'text-red-600 dark:text-red-300' : 'text-emerald-600 dark:text-emerald-300'}>
              {bullish ? '▲' : '▼'}
            </span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ActivityLedger({ summary, watchlist = [] }) {
  const signals = summary?.signals?.latest || []
  const holdings = summary?.positions?.items || []
  const nameBySymbol = new Map([
    ...signals.map((sig) => [sig.symbol, sig.name || sig.symbol]),
    ...watchlist.map((item) => [item.symbol, item.name || item.symbol]),
    ...holdings.map((h) => [h.symbol, h.name || h.symbol]),
  ])
  const items = [
    ...signals.slice(0, 5).map((sig) => ({
      time: formatDate(sig.date),
      kind: '信号',
      headline: `${nameBySymbol.get(sig.symbol) || sig.symbol} ${sig.recommendation}`,
      detail: `综合分 ${formatSignedNumber(sig.composite_score, 1)} · 技术 ${formatSignedNumber(sig.technical_score, 1)} · 情感 ${formatSignedNumber(sig.sentiment_score, 2)}`,
    })),
    ...holdings.slice(0, 3).map((h) => ({
      time: h.entry_date,
      kind: '持仓',
      headline: `${h.name || h.symbol} ${formatSignedPercent(h.pnl_pct)}`,
      detail: `止损 ${formatPrice(h.stop_loss)} · 止盈 ${formatPrice(h.take_profit)}`,
    })),
  ]
  return (
    <Section title="活动流水" eyebrow="事件时间线">
      <div className="space-y-3">
        {items.slice(0, 9).map((item, index) => (
          <div key={`${item.kind}-${index}`} className="grid grid-cols-[56px_48px_1fr] gap-3 border-b border-stone-300/70 pb-3 last:border-0 last:pb-0 dark:border-slate-700/80">
            <div className="font-mono text-xs text-stone-500 dark:text-slate-400">{item.time}</div>
            <div className="text-xs font-semibold text-cyan-700 dark:text-cyan-200">{item.kind}</div>
            <div>
              <div className="text-sm font-medium text-stone-950 dark:text-slate-100">{item.headline}</div>
              <div className="mt-1 text-xs text-stone-500 dark:text-slate-400">{item.detail}</div>
            </div>
          </div>
        ))}
      </div>
    </Section>
  )
}

function PositionOverview({ summary }) {
  const positions = summary?.positions || {}
  const items = positions.items || []
  return (
    <Section title="持仓情况" eyebrow="Portfolio">
      <div className="grid gap-4 lg:grid-cols-[0.8fr_1fr]">
        <div className="grid grid-cols-3 gap-2">
          <Metric label="持仓数" value={positions.count ?? 0} tone="cyan" />
          <Metric label="总市值" value={formatMoney(positions.market_value)} />
          <Metric label="总盈亏" value={formatSignedPercent(positions.pnl_pct)} tone={(positions.pnl || 0) >= 0 ? 'red' : 'green'} />
        </div>
        {items.length === 0 ? (
          <div className="rounded-sm border border-dashed border-stone-300 p-5 text-sm text-stone-500 dark:border-slate-700 dark:text-slate-400">
            暂无持仓数据。可以进入持仓设置页，或在 AI 对话里说“添加持仓 300308 100股 成本100”。
          </div>
        ) : (
          <div className="grid gap-2 md:grid-cols-2">
            {items.slice(0, 4).map((item) => (
              <Link key={item.id} to={`/stock/${item.symbol}`} className="rounded-sm border border-stone-300 bg-[#f3eddc] p-3 dark:border-slate-700 dark:bg-[#161b25]">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-stone-950 dark:text-slate-100">{item.name}</div>
                    <div className="font-mono text-xs text-stone-500 dark:text-slate-400">{item.symbol}</div>
                  </div>
                  <div className={`font-mono text-sm font-semibold ${(item.pnl || 0) >= 0 ? 'text-red-700 dark:text-red-200' : 'text-emerald-700 dark:text-emerald-200'}`}>{formatSignedPercent(item.pnl_pct)}</div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </Section>
  )
}

function MarketOverview({ summary }) {
  const market = summary?.market_overview || {}
  return (
    <Section title="大盘情况" eyebrow="Market">
      {market.available ? (
        <div className="grid grid-cols-3 gap-2">
          <Metric label={market.name || '沪深300'} value={formatMoney(market.close)} />
          <Metric label="涨跌幅" value={formatSignedPercent(market.change_pct)} tone={(market.change_pct || 0) >= 0 ? 'red' : 'green'} />
          <Metric label="日期" value={formatDate(market.date)} tone="cyan" />
        </div>
      ) : (
        <div className="rounded-sm border border-dashed border-stone-300 p-5 text-sm text-stone-500 dark:border-slate-700 dark:text-slate-400">
          暂无大盘指数数据，盘前同步后会显示沪深300状态。
        </div>
      )}
    </Section>
  )
}

function SignalTicker({ summary, watchlist }) {
  const signals = summary?.signals?.latest || watchlist.map((item) => item.latest_signal).filter(Boolean)
  return (
    <Section title="信号横条" eyebrow="最新横览">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {signals.slice(0, 8).map((sig) => {
          const stock = watchlist.find((item) => item.symbol === sig.symbol)
          return (
            <Link key={`${sig.symbol}-${sig.date}`} to={`/stock/${sig.symbol}`} className="rounded-sm border border-stone-300 bg-[#f3eddc] p-3 hover:border-cyan-600 dark:border-slate-700 dark:bg-[#161b25] dark:hover:border-cyan-400">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-sm font-semibold text-stone-950 dark:text-slate-100">{stock?.name || sig.symbol}</div>
                  <div className="mt-1 font-mono text-xs text-stone-500 dark:text-slate-400">{sig.symbol}</div>
                </div>
                <span className={`rounded-sm border px-2 py-0.5 text-[11px] font-semibold ${recClass(sig.recommendation)}`}>{sig.recommendation}</span>
              </div>
              <div className="mt-4 flex items-end justify-between">
                <div className="font-mono text-2xl font-semibold text-stone-950 dark:text-slate-100">{formatSignedNumber(sig.composite_score, 1)}</div>
                <MiniSpark score={sig.composite_score} />
              </div>
              {stock?.long_term_label?.label && (
                <div className="mt-3 flex items-center justify-between border-t border-stone-300/80 pt-2 text-xs dark:border-slate-700">
                  <span className="text-stone-500 dark:text-slate-400">长期标签</span>
                  <span className={`rounded-sm border px-2 py-0.5 font-semibold ${longTermClass(stock.long_term_label.label)}`}>
                    {stock.long_term_label.label}
                  </span>
                </div>
              )}
            </Link>
          )
        })}
      </div>
    </Section>
  )
}

function MiniSpark({ score }) {
  const up = Number(score || 0) >= 0
  const stroke = up ? '#dc2626' : '#059669'
  const points = up ? '0,28 18,20 36,23 54,10 72,14 90,4' : '0,8 18,12 36,9 54,21 72,18 90,28'
  return (
    <svg width="90" height="32" viewBox="0 0 90 32" aria-hidden="true">
      <polyline points={points} fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function WatchlistManage({ items, onRemove, onReload }) {
  const [query, setQuery] = useState('')
  const [market, setMarket] = useState('all')
  const [recommendation, setRecommendation] = useState('all')
  const filtered = filterWatchlistItems(items, { query, market, recommendation })
  const recommendations = Array.from(new Set(items.map((item) => item.latest_signal?.recommendation || '无信号'))).sort()
  return (
    <Section title="自选股管理" eyebrow="关注池" right={<AddStockForm onAdd={onReload} />}>
      <div className="mb-3 grid gap-2 md:grid-cols-[1fr_120px_150px_auto]">
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索代码、名称、行业" className="rounded-sm border border-stone-300 bg-[#fffaf0] px-3 py-2 text-xs outline-none focus:border-cyan-700 dark:border-slate-700 dark:bg-[#161b25]" />
        <select value={market} onChange={(e) => setMarket(e.target.value)} className="rounded-sm border border-stone-300 bg-[#fffaf0] px-2 py-2 text-xs outline-none dark:border-slate-700 dark:bg-[#161b25]">
          <option value="all">全部市场</option>
          <option value="CN">A股</option>
          <option value="HK">港股</option>
          <option value="US">美股</option>
        </select>
        <select value={recommendation} onChange={(e) => setRecommendation(e.target.value)} className="rounded-sm border border-stone-300 bg-[#fffaf0] px-2 py-2 text-xs outline-none dark:border-slate-700 dark:bg-[#161b25]">
          <option value="all">全部信号</option>
          {recommendations.map((rec) => <option key={rec} value={rec}>{rec}</option>)}
        </select>
        <div className="self-center text-right font-mono text-xs text-stone-500 dark:text-slate-400">{filtered.length}/{items.length}</div>
      </div>
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {filtered.map((item) => (
          <div key={item.symbol} className="flex items-center justify-between rounded-sm border border-stone-300 bg-[#f3eddc] px-3 py-2 dark:border-slate-700 dark:bg-[#161b25]">
            <Link to={`/stock/${item.symbol}`} className="min-w-0">
              <div className="truncate text-sm font-medium text-stone-950 dark:text-slate-100">{item.name}</div>
              <div className="font-mono text-xs text-stone-500 dark:text-slate-400">{item.symbol} · {item.industry || item.market}</div>
              {item.long_term_label?.label && (
                <div className={`mt-1 inline-flex rounded-sm border px-1.5 py-0.5 text-[10px] font-semibold ${longTermClass(item.long_term_label.label)}`}>
                  长期 {item.long_term_label.label}
                </div>
              )}
              {item.market !== 'CN' && !item.latest_signal && (
                <div className="mt-1 inline-flex rounded-sm border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 dark:text-amber-200">
                  观察
                </div>
              )}
            </Link>
            <button type="button" onClick={() => onRemove(item.symbol)} className="ml-2 h-6 w-6 rounded-sm border border-stone-300 text-stone-500 hover:border-red-500 hover:text-red-700 dark:border-slate-700 dark:text-slate-400 dark:hover:text-red-200" title="移除">
              ×
            </button>
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="col-span-full rounded-sm border border-dashed border-stone-300 p-5 text-sm text-stone-500 dark:border-slate-700 dark:text-slate-400">
            没有匹配的自选股
          </div>
        )}
      </div>
    </Section>
  )
}

function AddStockForm({ onAdd }) {
  const [open, setOpen] = useState(false)
  const [symbol, setSymbol] = useState('')
  const [name, setName] = useState('')
  const [market, setMarket] = useState('CN')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [suggestions, setSuggestions] = useState([])

  useEffect(() => {
    const query = symbol.trim() || name.trim()
    if (query.length < 2) {
      setSuggestions([])
      return
    }
    const id = setTimeout(() => {
      searchStocks(query, market).then(setSuggestions).catch(() => setSuggestions([]))
    }, 250)
    return () => clearTimeout(id)
  }, [symbol, name, market])

  function pick(item) {
    setSymbol(item.symbol)
    setName(item.name || item.symbol)
    setMarket(item.market || market)
    setSuggestions([])
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!symbol.trim() || !name.trim()) return
    setLoading(true)
    setError('')
    try {
      await addStock(symbol.trim(), name.trim(), market)
      setSymbol('')
      setName('')
      setOpen(false)
      onAdd()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="rounded-sm border border-stone-300 px-2.5 py-1 text-xs text-stone-600 hover:border-cyan-700 hover:text-cyan-700 dark:border-slate-700 dark:text-slate-300 dark:hover:border-cyan-400 dark:hover:text-cyan-200">
        添加标的
      </button>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="relative flex flex-wrap justify-end gap-2">
      <input value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="代码/名称" className="w-28 rounded-sm border border-stone-300 bg-[#fffaf0] px-2 py-1 text-xs outline-none dark:border-slate-700 dark:bg-[#161b25]" />
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder="名称" className="w-24 rounded-sm border border-stone-300 bg-[#fffaf0] px-2 py-1 text-xs outline-none dark:border-slate-700 dark:bg-[#161b25]" />
      <select value={market} onChange={(e) => setMarket(e.target.value)} className="rounded-sm border border-stone-300 bg-[#fffaf0] px-2 py-1 text-xs outline-none dark:border-slate-700 dark:bg-[#161b25]">
        <option value="CN">A股</option>
        <option value="HK">港股</option>
        <option value="US">美股</option>
      </select>
      <button type="submit" disabled={loading} className="rounded-sm bg-cyan-700 px-2.5 py-1 text-xs font-medium text-white disabled:opacity-50">{loading ? '保存中' : '保存'}</button>
      <button type="button" onClick={() => setOpen(false)} className="text-xs text-stone-500 dark:text-slate-400">取消</button>
      {error && <div className="basis-full text-right text-xs text-red-600">{error}</div>}
      {suggestions.length > 0 && (
        <div className="absolute right-0 top-8 z-10 w-56 overflow-hidden rounded-sm border border-stone-300 bg-[#fffaf0] shadow-xl dark:border-slate-700 dark:bg-[#161b25]">
          {suggestions.slice(0, 5).map((item) => (
            <button key={`${item.source}-${item.symbol}`} type="button" onClick={() => pick(item)} className="flex w-full items-center justify-between px-3 py-2 text-left text-xs hover:bg-cyan-700/10">
              <span>{item.name || item.symbol}</span>
              <span className="font-mono text-stone-500 dark:text-slate-400">{item.symbol}</span>
            </button>
          ))}
        </div>
      )}
    </form>
  )
}

export default function WatchlistPage() {
  const [items, setItems] = useState([])
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  async function load() {
    setLoading(true)
    setError('')
    try {
      const [watchlist, dashboard] = await Promise.all([
        getWatchlist(),
        getDashboardSummary().catch(() => null),
      ])
      setItems(watchlist)
      setSummary(dashboard)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function handleRemove(symbol) {
    if (!window.confirm(`从自选股移除 ${symbol}？`)) return
    await removeStock(symbol)
    load()
  }

  if (loading) return <div className="py-20 text-center text-sm text-stone-500 dark:text-slate-400">加载脉冲驾驶舱...</div>
  if (error) return <div className="py-20 text-center text-sm text-red-600">{error}</div>

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className={LABEL}>今日态势</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-stone-950 dark:text-slate-50">
            决策引擎收盘快照
          </h1>
        </div>
        <div className="font-mono text-xs text-stone-500 dark:text-slate-400">
          {summary?.signals?.latest_date || '暂无信号日期'} · {summary?.system?.profile || '-'}
        </div>
      </div>

      <ReleaseStatus />

      <TodayCall summary={summary} watchlist={items} />

      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          <PositionOverview summary={summary} />
          <MarketOverview summary={summary} />
          <SignalTicker summary={summary} watchlist={items} />
          <WatchlistManage items={items} onRemove={handleRemove} onReload={load} />
        </div>
        <ActivityLedger summary={summary} watchlist={items} />
      </div>
    </div>
  )
}
