import { useEffect, useMemo, useState } from 'react'
import { closePosition, createPosition, deleteClosedPosition, getPositions, searchStocks } from '../api'

const PANEL = 'rounded-sm border border-stone-300/80 bg-[#faf6ec] dark:border-slate-700 dark:bg-[#1d232e]'
const INSET = 'rounded-sm border border-stone-300 bg-[#f3eddc] dark:border-slate-700 dark:bg-[#161b25]'
const LABEL = 'text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500 dark:text-slate-400'

function money(value) {
  if (value === null || value === undefined) return '-'
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function signedPct(value) {
  if (value === null || value === undefined) return '-'
  const n = Number(value)
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`
}

function signedMoney(value) {
  if (value === null || value === undefined) return '-'
  const n = Number(value)
  return `${n > 0 ? '+' : ''}${money(n)}`
}

function PnlText({ value, children }) {
  const n = Number(value || 0)
  return (
    <span className={`font-mono font-semibold ${n >= 0 ? 'text-red-700 dark:text-red-200' : 'text-emerald-700 dark:text-emerald-200'}`}>
      {children}
    </span>
  )
}

function ClosePositionButton({ item, onClosed }) {
  const [open, setOpen] = useState(false)
  const [price, setPrice] = useState(item.latest_price || '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await closePosition(item.id, {
        close_price: Number(price),
        closed_at: new Date().toISOString().slice(0, 10),
      })
      setOpen(false)
      onClosed()
    } catch (err) {
      const message = String(err.message || '')
      setError(message.includes('404') ? '后端平仓接口未更新，请重启后端服务后再试。' : message)
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="rounded-sm border border-stone-300 px-3 py-1.5 text-xs font-semibold text-stone-600 hover:border-cyan-700 hover:text-cyan-700 dark:border-slate-700 dark:text-slate-300 dark:hover:border-cyan-300 dark:hover:text-cyan-200">
        平仓
      </button>
    )
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap items-center justify-end gap-2">
      <input
        value={price}
        onChange={(e) => setPrice(e.target.value)}
        placeholder="平仓价"
        className="w-24 rounded-sm border border-stone-300 bg-[#fffaf0] px-2 py-1.5 text-xs outline-none focus:border-cyan-700 dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-100"
      />
      <button disabled={busy || !price} className="rounded-sm bg-cyan-700 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">
        {busy ? '记录中' : '确认'}
      </button>
      <button type="button" onClick={() => setOpen(false)} className="rounded-sm border border-stone-300 px-2 py-1.5 text-xs text-stone-500 dark:border-slate-700 dark:text-slate-400">
        取消
      </button>
      {error && <div className="basis-full text-right text-xs text-red-600">{error}</div>}
    </form>
  )
}

function PositionForm({ onCreated }) {
  const [symbol, setSymbol] = useState('')
  const [name, setName] = useState('')
  const [market, setMarket] = useState('CN')
  const [quantity, setQuantity] = useState('')
  const [avgCost, setAvgCost] = useState('')
  const [suggestions, setSuggestions] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (symbol.trim().length < 2) {
      setSuggestions([])
      return
    }
    const id = setTimeout(() => {
      searchStocks(symbol.trim(), market).then(setSuggestions).catch(() => setSuggestions([]))
    }, 250)
    return () => clearTimeout(id)
  }, [symbol, market])

  function pick(item) {
    setSymbol(item.symbol)
    setName(item.name || item.symbol)
    setMarket(item.market || 'CN')
    setSuggestions([])
  }

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await createPosition({
        symbol: symbol.trim(),
        name: name.trim() || undefined,
        market,
        quantity: Number(quantity),
        avg_cost: Number(avgCost),
      })
      setSymbol('')
      setName('')
      setQuantity('')
      setAvgCost('')
      onCreated()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className={`${PANEL} p-4`}>
      <div className={LABEL}>持仓设置</div>
      <div className="mt-3 grid gap-3 md:grid-cols-[1fr_1fr_110px_110px_90px]">
        <div className="relative">
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="代码或名称" className="w-full rounded-sm border border-stone-300 bg-[#fffaf0] px-3 py-2 text-sm outline-none focus:border-cyan-700 dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-100" />
          {suggestions.length > 0 && (
            <div className="absolute z-10 mt-1 w-full overflow-hidden rounded-sm border border-stone-300 bg-[#fffaf0] shadow-xl dark:border-slate-700 dark:bg-[#161b25]">
              {suggestions.slice(0, 6).map((item) => (
                <button key={`${item.source}-${item.symbol}`} type="button" onClick={() => pick(item)} className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-cyan-700/10">
                  <span>{item.name || item.symbol}</span>
                  <span className="font-mono text-xs text-stone-500 dark:text-slate-400">{item.symbol}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="名称自动补全" className="rounded-sm border border-stone-300 bg-[#fffaf0] px-3 py-2 text-sm outline-none dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-100" />
        <input value={quantity} onChange={(e) => setQuantity(e.target.value)} placeholder="数量" className="rounded-sm border border-stone-300 bg-[#fffaf0] px-3 py-2 text-sm outline-none dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-100" />
        <input value={avgCost} onChange={(e) => setAvgCost(e.target.value)} placeholder="成本价" className="rounded-sm border border-stone-300 bg-[#fffaf0] px-3 py-2 text-sm outline-none dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-100" />
        <button disabled={busy || !symbol || !quantity || !avgCost} className="rounded-sm bg-cyan-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
          {busy ? '保存中' : '添加'}
        </button>
      </div>
      {error && <div className="mt-2 text-xs text-red-600">{error}</div>}
    </form>
  )
}

export default function PositionsPage() {
  const [positions, setPositions] = useState([])
  const [loading, setLoading] = useState(true)

  async function load() {
    setLoading(true)
    try {
      setPositions(await getPositions('all'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const openPositions = positions.filter((item) => item.status !== 'closed')
  const closedPositions = positions.filter((item) => item.status === 'closed')

  const total = useMemo(() => openPositions.reduce((acc, item) => ({
    market: acc.market + (item.market_value || 0),
    cost: acc.cost + (item.cost_value || 0),
    pnl: acc.pnl + (item.pnl || 0),
  }), { market: 0, cost: 0, pnl: 0 }), [positions])
  const realized = useMemo(() => closedPositions.reduce((acc, item) => acc + (item.realized_pnl || 0), 0), [positions])
  const totalPct = total.cost ? total.pnl / total.cost * 100 : null
  const overall = total.pnl + realized

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className={LABEL}>Portfolio</div>
            <h1 className="mt-1 text-2xl font-semibold text-stone-950 dark:text-slate-50">持仓设置</h1>
        </div>
        <div className="grid gap-1 text-right text-xs text-stone-500 dark:text-slate-400 sm:grid-cols-3 sm:gap-3">
          <div>持仓市值 <span className="font-mono text-stone-800 dark:text-slate-100">{money(total.market)}</span></div>
          <div>浮动盈亏 <PnlText value={total.pnl}>{signedMoney(total.pnl)} / {signedPct(totalPct)}</PnlText></div>
          <div>整体盈亏 <PnlText value={overall}>{signedMoney(overall)}</PnlText></div>
        </div>
      </div>
      <PositionForm onCreated={load} />
      <section className={PANEL}>
        <div className="border-b border-stone-300 p-4 dark:border-slate-700">
          <div className={LABEL}>Open Positions</div>
          <h2 className="mt-1 text-sm font-semibold text-stone-950 dark:text-slate-100">当前持仓</h2>
        </div>
        <div className="grid grid-cols-[1.2fr_0.8fr_0.8fr_0.8fr_0.8fr_auto] gap-3 border-b border-stone-300 px-4 py-3 text-xs font-semibold text-stone-500 dark:border-slate-700 dark:text-slate-400">
          <span>股票</span><span>数量</span><span>成本</span><span>最新价</span><span>盈亏</span><span />
        </div>
        {loading ? (
          <div className="p-8 text-center text-sm text-stone-500 dark:text-slate-400">加载持仓...</div>
        ) : openPositions.length === 0 ? (
          <div className="p-8 text-center text-sm text-stone-500 dark:text-slate-400">暂无持仓，可通过表单或 AI 对话添加。</div>
        ) : openPositions.map((item) => (
          <div key={item.id} className="grid grid-cols-[1.2fr_0.8fr_0.8fr_0.8fr_0.8fr_auto] items-center gap-3 border-b border-stone-300 px-4 py-3 text-sm last:border-0 dark:border-slate-700">
            <div>
              <div className="font-semibold text-stone-950 dark:text-slate-100">{item.name}</div>
              <div className="font-mono text-xs text-stone-500 dark:text-slate-400">{item.symbol}</div>
            </div>
            <span className="font-mono">{money(item.quantity)}</span>
            <span className="font-mono">{money(item.avg_cost)}</span>
            <span className="font-mono">{money(item.latest_price)}</span>
            <PnlText value={item.pnl}>{signedMoney(item.pnl)} / {signedPct(item.pnl_pct)}</PnlText>
            <ClosePositionButton item={item} onClosed={load} />
          </div>
        ))}
      </section>
      <section className={PANEL}>
        <div className="flex items-center justify-between border-b border-stone-300 p-4 dark:border-slate-700">
          <div>
            <div className={LABEL}>Closed Positions</div>
            <h2 className="mt-1 text-sm font-semibold text-stone-950 dark:text-slate-100">平仓记录</h2>
          </div>
          <PnlText value={realized}>已实现 {signedMoney(realized)}</PnlText>
        </div>
        {closedPositions.length === 0 ? (
          <div className="p-6 text-sm text-stone-500 dark:text-slate-400">暂无平仓记录</div>
        ) : (
          <div className="divide-y divide-stone-300 dark:divide-slate-700">
            {closedPositions.map((item) => (
              <div key={item.id} className="grid gap-3 p-4 text-sm md:grid-cols-[1.1fr_0.8fr_0.8fr_0.8fr_0.8fr]">
                <div>
                  <div className="font-semibold text-stone-950 dark:text-slate-100">{item.name}</div>
                  <div className="font-mono text-xs text-stone-500 dark:text-slate-400">{item.symbol} · {item.opened_at} → {item.closed_at || '-'}</div>
                </div>
                <span className="font-mono">数量 {money(item.quantity)}</span>
                <span className="font-mono">成本 {money(item.avg_cost)}</span>
                <span className="font-mono">平仓 {money(item.close_price)}</span>
                <div className="flex flex-wrap items-center justify-between gap-2 md:justify-end">
                  <PnlText value={item.realized_pnl}>{signedMoney(item.realized_pnl)} / {signedPct(item.realized_pnl_pct)}</PnlText>
                  <button
                    onClick={async () => {
                      if (!window.confirm(`永久删除 ${item.symbol} 的平仓记录？`)) return
                      await deleteClosedPosition(item.id)
                      load()
                    }}
                    className="rounded-sm border border-stone-300 px-2 py-1 text-xs text-stone-500 hover:border-red-600 hover:text-red-700 dark:border-slate-700 dark:text-slate-400 dark:hover:border-red-300 dark:hover:text-red-200"
                  >
                    删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
