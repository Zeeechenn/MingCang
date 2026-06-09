import { useEffect, useState } from 'react'
import { getDataCoverage } from '../api'
import { getDataTrustSummary } from '../components/evidenceSummary'

const PANEL = 'rounded-sm border border-stone-300/80 bg-[#faf6ec] dark:border-slate-700 dark:bg-[#1d232e]'
const INSET = 'rounded-sm border border-stone-300 bg-[#f3eddc] dark:border-slate-700 dark:bg-[#161b25]'
const LABEL = 'text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500 dark:text-slate-400'

function StatusBadge({ status }) {
  const style =
    status === 'pass'
      ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
      : status === 'warning'
      ? 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300'
      : 'border-stone-300 bg-stone-100 text-stone-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400'
  return (
    <span className={`inline-flex rounded-sm border px-2 py-0.5 text-[11px] font-semibold ${style}`}>
      {status === 'pass' ? '通过' : status === 'warning' ? '需复核' : '未知'}
    </span>
  )
}

function ProviderChainRow({ market, chain }) {
  if (!chain || chain.length === 0) {
    return (
      <div className="py-2 text-xs text-stone-400 dark:text-slate-500">
        暂无回退链配置
      </div>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {chain.map((name, idx) => (
        <div key={`${market}-${name}-${idx}`} className="flex items-center gap-1">
          <span className={`${INSET} px-2.5 py-1 font-mono text-xs text-stone-700 dark:text-slate-200`}>
            {name}
          </span>
          {idx < chain.length - 1 && (
            <span className="text-xs text-stone-400 dark:text-slate-500">→</span>
          )}
        </div>
      ))}
    </div>
  )
}

function MarketHealthCard({ market, coverage }) {
  const summary = getDataTrustSummary(coverage, null)
  // Override market in summary by rebuilding with the right market context
  const chains = coverage?.provider_fallback_chains?.chains_by_market
    || coverage?.summary?.provider_fallback_chains?.chains_by_market
    || {}
  const dailyChain = chains?.[market]?.daily?.map((p) => p?.name).filter(Boolean) || []
  const freshnessContract = coverage?.freshness_contract?.daily_price
    || coverage?.summary?.freshness_contract?.daily_price
    || {}
  const policy = freshnessContract.intraday_policy || freshnessContract.policy || null
  const maxLagDays = freshnessContract.max_lag_days ?? null

  const MARKET_LABELS = { CN: 'A股', HK: '港股', US: '美股' }

  return (
    <div className={`${PANEL} overflow-hidden`}>
      <div className="flex items-center justify-between border-b border-stone-300/80 px-4 py-3 dark:border-slate-700">
        <div>
          <div className={LABEL}>市场</div>
          <h3 className="mt-0.5 text-sm font-semibold text-stone-950 dark:text-slate-100">
            {MARKET_LABELS[market] || market}
          </h3>
        </div>
        <StatusBadge status={summary.status} />
      </div>
      <div className="space-y-4 p-4">
        <div>
          <div className={LABEL + ' mb-2'}>提供商回退链（日线）</div>
          <ProviderChainRow market={market} chain={dailyChain} />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <div className={LABEL}>盘中策略</div>
            <div className="mt-1 text-sm text-stone-700 dark:text-slate-300">
              {policy || '暂无配置'}
            </div>
          </div>
          {maxLagDays !== null && (
            <div>
              <div className={LABEL}>最大允许滞后</div>
              <div className="mt-1 font-mono text-sm text-stone-700 dark:text-slate-300">
                {maxLagDays} 天
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function WarningsPanel({ warnings }) {
  if (!warnings || warnings.length === 0) {
    return (
      <div className="rounded-sm border border-dashed border-stone-300 px-4 py-5 text-sm text-stone-500 dark:border-slate-700 dark:text-slate-400">
        暂无数据警告，所有检查均通过。
      </div>
    )
  }
  return (
    <div className="space-y-2">
      {warnings.map((w, idx) => (
        <div
          key={idx}
          className="flex items-start gap-3 rounded-sm border border-amber-400/40 bg-amber-400/5 px-4 py-3 dark:border-amber-300/20 dark:bg-amber-300/5"
        >
          <span className="mt-0.5 text-amber-600 dark:text-amber-300">▲</span>
          <div>
            {w.code && (
              <div className="font-mono text-[11px] font-semibold text-amber-700 dark:text-amber-300">
                {w.code}
              </div>
            )}
            <div className="mt-0.5 text-xs text-stone-700 dark:text-slate-300">
              {w.message || w.detail || String(w)}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

function ChecksPanel({ checks }) {
  const entries = Object.entries(checks || {})
  if (entries.length === 0) {
    return (
      <div className="text-sm text-stone-500 dark:text-slate-400">
        暂无检查项数据。
      </div>
    )
  }
  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {entries.map(([key, value]) => (
        <div key={key} className={`${INSET} flex items-center justify-between px-3 py-2`}>
          <span className="text-xs text-stone-600 dark:text-slate-300">{key}</span>
          <span className={`font-mono text-xs font-semibold ${value ? 'text-emerald-700 dark:text-emerald-300' : 'text-amber-700 dark:text-amber-300'}`}>
            {value ? 'pass' : 'fail'}
          </span>
        </div>
      ))}
    </div>
  )
}

function StockCoverageTable({ stocks }) {
  if (!stocks || stocks.length === 0) {
    return (
      <div className="rounded-sm border border-dashed border-stone-300 px-4 py-5 text-sm text-stone-500 dark:border-slate-700 dark:text-slate-400">
        暂无标的覆盖数据。添加自选股后，系统会在下次数据拉取时更新覆盖状态。
      </div>
    )
  }
  return (
    <div className="overflow-x-auto rounded-sm border border-stone-300/80 dark:border-slate-700">
      <table className="min-w-full border-collapse text-left text-xs">
        <thead className="bg-[#f3eddc] text-stone-600 dark:bg-[#161b25] dark:text-slate-300">
          <tr>
            <th className="border-b border-stone-300 px-3 py-2 font-semibold dark:border-slate-700">代码</th>
            <th className="border-b border-stone-300 px-3 py-2 font-semibold dark:border-slate-700">名称</th>
            <th className="border-b border-stone-300 px-3 py-2 font-semibold dark:border-slate-700">市场</th>
            <th className="border-b border-stone-300 px-3 py-2 font-semibold dark:border-slate-700">最新价格日期</th>
            <th className="border-b border-stone-300 px-3 py-2 font-semibold dark:border-slate-700">状态</th>
          </tr>
        </thead>
        <tbody>
          {stocks.map((row) => (
            <tr key={row.symbol} className="odd:bg-white/30 dark:odd:bg-slate-950/20">
              <td className="border-b border-stone-200 px-3 py-2 font-mono dark:border-slate-800">{row.symbol}</td>
              <td className="border-b border-stone-200 px-3 py-2 dark:border-slate-800">{row.name || '-'}</td>
              <td className="border-b border-stone-200 px-3 py-2 dark:border-slate-800">{row.market || '-'}</td>
              <td className="border-b border-stone-200 px-3 py-2 font-mono dark:border-slate-800">
                {row.latest_price_date || '暂无'}
              </td>
              <td className="border-b border-stone-200 px-3 py-2 dark:border-slate-800">
                <StatusBadge status={row.status === 'ok' ? 'pass' : row.status === 'warning' ? 'warning' : 'unknown'} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function DataHealthPage() {
  const [coverage, setCoverage] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    setError('')
    getDataCoverage()
      .then(setCoverage)
      .catch((e) => setError(e?.message || '无法加载数据健康信息'))
      .finally(() => setLoading(false))
  }, [])

  const summary = getDataTrustSummary(coverage || {}, null)
  const warnings = Array.isArray(coverage?.warnings) ? coverage.warnings : []
  const checks = coverage?.checks || {}
  const stocks = Array.isArray(coverage?.stocks) ? coverage.stocks : []
  const MARKETS = ['CN', 'HK', 'US']

  return (
    <div className="space-y-5">
      {/* Page header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className={LABEL}>系统</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-stone-950 dark:text-slate-50">
            数据健康
          </h1>
          <p className="mt-1 text-sm text-stone-500 dark:text-slate-400">
            各数据源状态、提供商回退链、新鲜度策略与告警。本页只读，不触发任何数据拉取。
          </p>
        </div>
        {!loading && (
          <div className="flex items-center gap-2">
            <span className={LABEL}>整体状态</span>
            <StatusBadge status={summary.status} />
          </div>
        )}
      </div>

      {loading && (
        <div className="py-16 text-center text-sm text-stone-500 dark:text-slate-400">
          加载数据健康信息…
        </div>
      )}

      {!loading && error && (
        <div className="rounded-sm border border-red-300/60 bg-red-50 px-4 py-4 text-sm text-red-700 dark:border-red-700/40 dark:bg-red-900/10 dark:text-red-300">
          <div className="font-semibold">无法加载数据</div>
          <div className="mt-1 text-xs">{error}</div>
          <div className="mt-2 text-xs text-stone-500 dark:text-slate-400">
            确认后端服务正在运行，然后刷新页面重试。
          </div>
        </div>
      )}

      {!loading && !error && (
        <>
          {/* Per-market provider chains */}
          <section className={PANEL}>
            <div className="border-b border-stone-300/80 px-4 py-3 dark:border-slate-700">
              <div className={LABEL}>数据源</div>
              <h2 className="mt-0.5 text-sm font-semibold text-stone-950 dark:text-slate-100">
                各市场提供商回退链
              </h2>
            </div>
            <div className="grid gap-4 p-4 lg:grid-cols-3">
              {MARKETS.map((market) => (
                <MarketHealthCard key={market} market={market} coverage={coverage || {}} />
              ))}
            </div>
          </section>

          {/* Checks */}
          <section className={PANEL}>
            <div className="border-b border-stone-300/80 px-4 py-3 dark:border-slate-700">
              <div className={LABEL}>检查项</div>
              <h2 className="mt-0.5 text-sm font-semibold text-stone-950 dark:text-slate-100">
                数据完整性检查
              </h2>
            </div>
            <div className="p-4">
              <ChecksPanel checks={checks} />
            </div>
          </section>

          {/* Warnings */}
          <section className={PANEL}>
            <div className="flex items-center justify-between border-b border-stone-300/80 px-4 py-3 dark:border-slate-700">
              <div>
                <div className={LABEL}>警告</div>
                <h2 className="mt-0.5 text-sm font-semibold text-stone-950 dark:text-slate-100">
                  当前数据告警
                </h2>
              </div>
              {warnings.length > 0 && (
                <span className="rounded-sm border border-amber-400/50 bg-amber-400/10 px-2 py-0.5 font-mono text-xs font-semibold text-amber-700 dark:text-amber-300">
                  {warnings.length} 条
                </span>
              )}
            </div>
            <div className="p-4">
              <WarningsPanel warnings={warnings} />
            </div>
          </section>

          {/* Per-stock coverage */}
          <section className={PANEL}>
            <div className="border-b border-stone-300/80 px-4 py-3 dark:border-slate-700">
              <div className={LABEL}>标的覆盖</div>
              <h2 className="mt-0.5 text-sm font-semibold text-stone-950 dark:text-slate-100">
                自选股数据覆盖状态
              </h2>
            </div>
            <div className="p-4">
              <StockCoverageTable stocks={stocks} />
            </div>
          </section>
        </>
      )}
    </div>
  )
}
