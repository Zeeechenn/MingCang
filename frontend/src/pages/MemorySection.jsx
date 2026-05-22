import { useCallback, useEffect, useState } from 'react'
import {
  archiveStockMemory,
  deleteMemory,
  deleteStockMemory,
  getMemoryAudit,
  getMemoryLayered,
  getMemoryList,
  getMemoryOverview,
  getStockMemoryItems,
  patchMemory,
  patchStockMemory,
  pinMemory,
} from '../api'

const PANEL = 'rounded-sm border border-stone-300 bg-[#faf6ec] dark:border-slate-700 dark:bg-[#1d232e]'
const INSET = 'rounded-sm border border-stone-300 bg-[#f3eddc] dark:border-slate-700 dark:bg-[#161b25]'
const LABEL = 'text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500 dark:text-slate-400'

function truncate(text, n = 80) {
  if (!text) return ''
  return text.length > n ? text.slice(0, n) + '…' : text
}

function StatTile({ label, value }) {
  return (
    <div className={`${INSET} p-3`}>
      <div className={LABEL}>{label}</div>
      <div className="mt-1 font-mono text-lg font-semibold text-stone-950 dark:text-slate-100">{value}</div>
    </div>
  )
}

function OverviewPanel({ overview }) {
  if (!overview) return <div className={`${INSET} p-4 text-sm text-stone-500 dark:text-slate-400`}>加载中…</div>
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <StatTile label="活跃记忆数" value={overview.total_active} />
      <StatTile label="分层记忆行数" value={overview.layered_rows} />
      <StatTile label="范围数" value={Object.keys(overview.by_scope || {}).length} />
      <StatTile label="最近更新" value={overview.last_updated ? overview.last_updated.slice(0, 19) : '—'} />
      <div className={`${INSET} p-3 sm:col-span-2`}>
        <div className={LABEL}>按 scope</div>
        <div className="mt-1 flex flex-wrap gap-2 font-mono text-xs">
          {Object.entries(overview.by_scope || {}).map(([k, v]) => (
            <span key={k} className="rounded-sm bg-stone-200 px-2 py-1 dark:bg-slate-800">
              {k} · {v}
            </span>
          ))}
        </div>
      </div>
      <div className={`${INSET} p-3 sm:col-span-2`}>
        <div className={LABEL}>按 category</div>
        <div className="mt-1 flex flex-wrap gap-2 font-mono text-xs">
          {Object.entries(overview.by_category || {}).map(([k, v]) => (
            <span key={k} className="rounded-sm bg-stone-200 px-2 py-1 dark:bg-slate-800">
              {k} · {v}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

function MemoryRow({ row, onChange }) {
  const [busy, setBusy] = useState(false)

  const run = async (fn) => {
    setBusy(true)
    try {
      await fn()
      await onChange()
    } catch (e) {
      window.alert(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  const onPin = () => {
    if (!window.confirm(`固定 "${row.key}" 永不过期？`)) return
    run(() => pinMemory(row.id))
  }
  const onDelete = () => {
    if (!window.confirm(`删除 "${row.key}"？删除后仍可从每日备份恢复。`)) return
    run(() => deleteMemory(row.id))
  }
  const onChangeTTL = () => {
    const raw = window.prompt(`新 TTL（天）。留空清除 TTL；当前 ${row.ttl_days ?? '永不过期'}`, row.ttl_days ?? '')
    if (raw === null) return
    if (raw === '') {
      run(() => patchMemory(row.id, { clear_ttl: true }))
    } else {
      const n = Number(raw)
      if (!Number.isFinite(n) || n < 0) return window.alert('无效 TTL 数值')
      run(() => patchMemory(row.id, { ttl_days: n }))
    }
  }
  const onChangeCategory = () => {
    const next = window.prompt('新 category', row.category ?? '')
    if (next === null || next === row.category) return
    run(() => patchMemory(row.id, { category: next }))
  }

  return (
    <tr className="border-t border-stone-300 align-top text-sm dark:border-slate-700">
      <td className="px-3 py-2 font-mono text-xs">{row.scope}</td>
      <td className="px-3 py-2 font-mono text-xs">{row.category ?? '—'}</td>
      <td className="px-3 py-2 font-mono text-xs">{row.key}</td>
      <td className="px-3 py-2 text-xs text-stone-500 dark:text-slate-400" title={row.value}>{truncate(row.value)}</td>
      <td className="px-3 py-2 font-mono text-xs">{row.ttl_days ?? '∞'}</td>
      <td className="px-3 py-2 font-mono text-[11px] text-stone-500 dark:text-slate-400">{row.updated_at?.slice(0, 19) || '—'}</td>
      <td className="px-3 py-2 whitespace-nowrap text-xs">
        <button type="button" disabled={busy} onClick={onPin} className="mr-2 underline">固定</button>
        <button type="button" disabled={busy} onClick={onChangeTTL} className="mr-2 underline">TTL</button>
        <button type="button" disabled={busy} onClick={onChangeCategory} className="mr-2 underline">cat</button>
        <button type="button" disabled={busy} onClick={onDelete} className="text-red-600 underline dark:text-red-400">删除</button>
      </td>
    </tr>
  )
}

function MemoryTable({ rows, onChange }) {
  if (rows.length === 0) {
    return <div className={`${INSET} p-4 text-sm text-stone-500 dark:text-slate-400`}>无匹配记忆。</div>
  }
  return (
    <div className={`${INSET} overflow-x-auto`}>
      <table className="w-full text-left">
        <thead className="text-[10px] uppercase tracking-[0.18em] text-stone-500 dark:text-slate-400">
          <tr>
            <th className="px-3 py-2">scope</th>
            <th className="px-3 py-2">category</th>
            <th className="px-3 py-2">key</th>
            <th className="px-3 py-2">value</th>
            <th className="px-3 py-2">TTL</th>
            <th className="px-3 py-2">updated</th>
            <th className="px-3 py-2">操作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => <MemoryRow key={r.id} row={r} onChange={onChange} />)}
        </tbody>
      </table>
    </div>
  )
}

function StockMemoryRow({ row, onChange }) {
  const [busy, setBusy] = useState(false)

  const run = async (fn) => {
    setBusy(true)
    try {
      await fn()
      await onChange()
    } catch (e) {
      window.alert(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  const onArchive = () => {
    if (!window.confirm(`归档股票记忆 #${row.id}？`)) return
    run(() => archiveStockMemory(row.id))
  }
  const onDelete = () => {
    if (!window.confirm(`删除股票记忆 #${row.id}？`)) return
    run(() => deleteStockMemory(row.id))
  }
  const onChangeTTL = () => {
    const raw = window.prompt(`新 TTL（天）。留空清除 TTL；当前 ${row.ttl_days ?? '永不过期'}`, row.ttl_days ?? '')
    if (raw === null) return
    if (raw === '') {
      run(() => patchStockMemory(row.id, { clear_ttl: true }))
    } else {
      const n = Number(raw)
      if (!Number.isFinite(n) || n < 0) return window.alert('无效 TTL 数值')
      run(() => patchStockMemory(row.id, { ttl_days: n }))
    }
  }
  const onChangeImportance = () => {
    const raw = window.prompt('重要度 1-5', row.importance ?? 3)
    if (raw === null) return
    const n = Number(raw)
    if (!Number.isFinite(n) || n < 1 || n > 5) return window.alert('重要度必须是 1-5')
    run(() => patchStockMemory(row.id, { importance: n }))
  }
  const onChangeStatus = () => {
    const next = window.prompt('status: active / watching / validated / refuted / archived', row.status ?? 'active')
    if (next === null || next === row.status) return
    run(() => patchStockMemory(row.id, { status: next }))
  }

  return (
    <tr className="border-t border-stone-300 align-top text-sm dark:border-slate-700">
      <td className="px-3 py-2 font-mono text-xs">{row.symbol ?? '全局'}</td>
      <td className="px-3 py-2 font-mono text-xs">{row.memory_type}</td>
      <td className="px-3 py-2 font-mono text-xs">{row.status}</td>
      <td className="px-3 py-2 text-xs text-stone-500 dark:text-slate-400" title={row.summary}>{truncate(row.summary, 110)}</td>
      <td className="px-3 py-2 font-mono text-xs">{row.importance}</td>
      <td className="px-3 py-2 font-mono text-xs">{row.ttl_days ?? '∞'}</td>
      <td className="px-3 py-2 font-mono text-[11px] text-stone-500 dark:text-slate-400">{row.updated_at?.slice(0, 19) || '—'}</td>
      <td className="px-3 py-2 whitespace-nowrap text-xs">
        <button type="button" disabled={busy} onClick={onArchive} className="mr-2 underline">归档</button>
        <button type="button" disabled={busy} onClick={onChangeTTL} className="mr-2 underline">TTL</button>
        <button type="button" disabled={busy} onClick={onChangeImportance} className="mr-2 underline">重要度</button>
        <button type="button" disabled={busy} onClick={onChangeStatus} className="mr-2 underline">status</button>
        <button type="button" disabled={busy} onClick={onDelete} className="text-red-600 underline dark:text-red-400">删除</button>
      </td>
    </tr>
  )
}

function StockMemoryTable({ rows, onChange }) {
  if (rows.length === 0) {
    return <div className={`${INSET} p-4 text-sm text-stone-500 dark:text-slate-400`}>无匹配股票记忆。</div>
  }
  return (
    <div className={`${INSET} overflow-x-auto`}>
      <table className="w-full text-left">
        <thead className="text-[10px] uppercase tracking-[0.18em] text-stone-500 dark:text-slate-400">
          <tr>
            <th className="px-3 py-2">symbol</th>
            <th className="px-3 py-2">type</th>
            <th className="px-3 py-2">status</th>
            <th className="px-3 py-2">summary</th>
            <th className="px-3 py-2">重要度</th>
            <th className="px-3 py-2">TTL</th>
            <th className="px-3 py-2">updated</th>
            <th className="px-3 py-2">操作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => <StockMemoryRow key={r.id} row={r} onChange={onChange} />)}
        </tbody>
      </table>
    </div>
  )
}

function LayeredPanel({ rows }) {
  if (!rows || rows.length === 0) {
    return <div className={`${INSET} p-3 text-xs text-stone-500 dark:text-slate-400`}>暂无分层决策记忆（medium/long）。</div>
  }
  return (
    <div className={`${INSET} overflow-x-auto`}>
      <table className="w-full text-left text-xs">
        <thead className="text-[10px] uppercase tracking-[0.18em] text-stone-500 dark:text-slate-400">
          <tr>
            <th className="px-3 py-2">layer</th>
            <th className="px-3 py-2">symbol</th>
            <th className="px-3 py-2">大小</th>
            <th className="px-3 py-2">updated</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-stone-300 dark:border-slate-700">
              <td className="px-3 py-2 font-mono">{r.layer}</td>
              <td className="px-3 py-2 font-mono">{r.symbol ?? '全局'}</td>
              <td className="px-3 py-2 font-mono">{r.size} B</td>
              <td className="px-3 py-2 font-mono text-stone-500 dark:text-slate-400">{r.updated_at?.slice(0, 19) || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AuditPanel() {
  const [q, setQ] = useState('')
  const [rows, setRows] = useState([])
  const [busy, setBusy] = useState(false)

  const search = async () => {
    if (!q.trim()) return
    setBusy(true)
    try {
      const r = await getMemoryAudit(q.trim())
      setRows(r.rows || [])
    } catch (e) {
      window.alert(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <input
          type="text"
          placeholder="FTS5 关键词（key / scope / category 等）"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') search() }}
          className="flex-1 rounded-sm border border-stone-300 bg-[#fffaf0] px-3 py-2 text-sm dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-100"
        />
        <button type="button" onClick={search} disabled={busy} className="rounded-sm bg-cyan-700 px-3 py-1 text-xs font-semibold text-white dark:bg-cyan-400 dark:text-slate-950">
          搜索
        </button>
      </div>
      {rows.length === 0 ? (
        <div className={`${INSET} p-3 text-xs text-stone-500 dark:text-slate-400`}>输入关键词后回车 / 点搜索。审计仅记录写/读/删/固定/改/备份事件。</div>
      ) : (
        <div className={`${INSET} max-h-96 overflow-y-auto`}>
          <table className="w-full text-left text-xs">
            <thead className="text-[10px] uppercase tracking-[0.18em] text-stone-500 dark:text-slate-400">
              <tr>
                <th className="px-3 py-2">timestamp</th>
                <th className="px-3 py-2">event</th>
                <th className="px-3 py-2">scope/symbol</th>
                <th className="px-3 py-2">content</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-stone-300 dark:border-slate-700">
                  <td className="px-3 py-2 font-mono">{r.timestamp}</td>
                  <td className="px-3 py-2 font-mono">{r.event_type}</td>
                  <td className="px-3 py-2 font-mono">{r.related_symbol || r.related_scope || '—'}</td>
                  <td className="px-3 py-2 text-stone-500 dark:text-slate-400">{r.content}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function MemorySection() {
  const [overview, setOverview] = useState(null)
  const [rows, setRows] = useState([])
  const [stockRows, setStockRows] = useState([])
  const [layered, setLayered] = useState([])
  const [scope, setScope] = useState('')
  const [category, setCategory] = useState('')
  const [q, setQ] = useState('')
  const [stockSymbol, setStockSymbol] = useState('')
  const [stockType, setStockType] = useState('')
  const [stockStatus, setStockStatus] = useState('')
  const [stockQ, setStockQ] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    setBusy(true)
    try {
      const [o, l, le, sm] = await Promise.all([
        getMemoryOverview(),
        getMemoryList({ scope, category, q }),
        getMemoryLayered(),
        getStockMemoryItems({ symbol: stockSymbol, type: stockType, status: stockStatus, q: stockQ }),
      ])
      setOverview(o)
      setRows(l.rows || [])
      setLayered(le.rows || [])
      setStockRows(sm.rows || [])
    } catch (e) {
      console.error(e)
    } finally {
      setBusy(false)
    }
  }, [scope, category, q, stockSymbol, stockType, stockStatus, stockQ])

  useEffect(() => { refresh() }, [refresh])

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <h3 className={LABEL}>概览</h3>
        <OverviewPanel overview={overview} />
      </section>

      <section className="space-y-3">
        <h3 className={LABEL}>记忆列表（受控编辑：删除 / 固定 / 改 TTL / 改 category。**不**支持编辑原文）</h3>
        <div className={`${PANEL} p-4`}>
          <div className="mb-3 grid gap-2 sm:grid-cols-[160px_160px_1fr_auto]">
            <input type="text" placeholder="scope" value={scope} onChange={(e) => setScope(e.target.value)}
              className="rounded-sm border border-stone-300 bg-[#fffaf0] px-3 py-2 text-sm dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-100" />
            <input type="text" placeholder="category" value={category} onChange={(e) => setCategory(e.target.value)}
              className="rounded-sm border border-stone-300 bg-[#fffaf0] px-3 py-2 text-sm dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-100" />
            <input type="text" placeholder="key / value 关键词" value={q} onChange={(e) => setQ(e.target.value)}
              className="rounded-sm border border-stone-300 bg-[#fffaf0] px-3 py-2 text-sm dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-100" />
            <button type="button" onClick={refresh} disabled={busy} className="rounded-sm bg-cyan-700 px-3 py-1 text-xs font-semibold text-white dark:bg-cyan-400 dark:text-slate-950">
              {busy ? '加载…' : '刷新'}
            </button>
          </div>
          <MemoryTable rows={rows} onChange={refresh} />
        </div>
      </section>

      <section className="space-y-3">
        <h3 className={LABEL}>分层决策记忆（只读）</h3>
        <LayeredPanel rows={layered} />
      </section>

      <section className="space-y-3">
        <h3 className={LABEL}>股票长期记忆（受控编辑：归档 / 删除 / 改 TTL / 改重要度 / 改 status。**不**支持编辑原文）</h3>
        <div className={`${PANEL} p-4`}>
          <div className="mb-3 grid gap-2 sm:grid-cols-[120px_150px_150px_1fr_auto]">
            <input type="text" placeholder="symbol" value={stockSymbol} onChange={(e) => setStockSymbol(e.target.value)}
              className="rounded-sm border border-stone-300 bg-[#fffaf0] px-3 py-2 text-sm dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-100" />
            <input type="text" placeholder="type" value={stockType} onChange={(e) => setStockType(e.target.value)}
              className="rounded-sm border border-stone-300 bg-[#fffaf0] px-3 py-2 text-sm dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-100" />
            <input type="text" placeholder="status" value={stockStatus} onChange={(e) => setStockStatus(e.target.value)}
              className="rounded-sm border border-stone-300 bg-[#fffaf0] px-3 py-2 text-sm dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-100" />
            <input type="text" placeholder="summary / evidence 关键词" value={stockQ} onChange={(e) => setStockQ(e.target.value)}
              className="rounded-sm border border-stone-300 bg-[#fffaf0] px-3 py-2 text-sm dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-100" />
            <button type="button" onClick={refresh} disabled={busy} className="rounded-sm bg-cyan-700 px-3 py-1 text-xs font-semibold text-white dark:bg-cyan-400 dark:text-slate-950">
              {busy ? '加载…' : '刷新'}
            </button>
          </div>
          <StockMemoryTable rows={stockRows} onChange={refresh} />
        </div>
      </section>

      <section className="space-y-3">
        <h3 className={LABEL}>召回日志（audit）</h3>
        <AuditPanel />
      </section>
    </div>
  )
}
