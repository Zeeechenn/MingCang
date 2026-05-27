import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  getLatestSignal,
  getPrices,
  getNews,
  getSignalEval,
  getSignalEvidence,
  getResearchDossier,
  getResearchState,
  getDataCoverage,
  getLongTermLabel,
  getSignals,
  reviewLatestSignal,
  refreshResearchCopilot,
} from '../api'
import SignalCard from '../components/SignalCard'
import SignalEvalCard from '../components/SignalEvalCard'
import Chart from '../components/Chart'
import NewsSidebar from '../components/NewsSidebar'
import EvidenceCard from '../components/EvidenceCard'
import ResearchCopilotCard from '../components/ResearchCopilotCard'
import { getDossierActionView } from '../components/dossierSummary'
import {
  createSecondaryLoadingStatus,
  hasSecondaryLoading,
  markStockDetailSection,
} from './stockDetailProgress'

const PANEL = 'rounded-sm border border-stone-300/80 bg-[#faf6ec] dark:border-slate-700 dark:bg-[#1d232e]'
const INSET = 'rounded-sm border border-stone-300 bg-[#f3eddc] dark:border-slate-700 dark:bg-[#161b25]'
const LABEL = 'text-[10px] font-semibold uppercase tracking-[0.18em] text-stone-500 dark:text-slate-400'

function signed(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-'
  const n = Number(value)
  return `${n > 0 ? '+' : ''}${n.toFixed(digits)}`
}

function labelTone(label) {
  if (label === '值得持有') return 'border-red-500/35 bg-red-500/10 text-red-700 dark:text-red-200'
  if (label === '估值偏高') return 'border-amber-500/35 bg-amber-500/10 text-amber-700 dark:text-amber-200'
  if (label === '规避') return 'border-emerald-500/35 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200'
  return 'border-cyan-600/30 bg-cyan-600/10 text-cyan-700 dark:text-cyan-200'
}

function conflictTone(severity) {
  if (severity === 'high') return 'border-red-500/35 bg-red-500/10 text-red-700 dark:text-red-200'
  if (severity === 'medium') return 'border-amber-500/35 bg-amber-500/10 text-amber-700 dark:text-amber-200'
  return 'border-cyan-600/30 bg-cyan-600/10 text-cyan-700 dark:text-cyan-200'
}

function labelQualityView(label) {
  if (!label) return null
  if (label.constraint_eligible) {
    return {
      text: '已通过质量门，可约束官方动作',
      tone: 'border-cyan-600/30 bg-cyan-600/10 text-cyan-700 dark:text-cyan-200',
    }
  }
  return {
    text: label.quality === 'failed' ? '待复核，仅展示，不约束官方动作' : '证据不足，仅展示，不约束官方动作',
    tone: 'border-amber-500/35 bg-amber-500/10 text-amber-700 dark:text-amber-200',
  }
}

function DossierPanel({ dossier, signal }) {
  const view = getDossierActionView(dossier || {}, signal || {})
  const constraints = view.constraints
  const conflicts = view.conflicts
  return (
    <section className={PANEL}>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-stone-300/80 p-4 dark:border-slate-700">
        <div>
          <div className={LABEL}>研究档案</div>
          <h2 className="mt-1 text-sm font-semibold text-stone-950 dark:text-slate-100">官方动作与约束</h2>
        </div>
        <div className="text-right">
          <div className="text-xs text-stone-500 dark:text-slate-400">{signal?.date || '-'}</div>
          <div className="mt-1 text-sm font-semibold text-stone-950 dark:text-slate-100">
            {view.recommendation}
          </div>
        </div>
      </div>
      <div className="grid gap-3 p-4 md:grid-cols-3">
        <div className={INSET}>
          <div className="p-3">
            <div className={LABEL}>最终仓位</div>
            <div className="mt-2 font-mono text-xl font-semibold text-stone-950 dark:text-slate-100">
              {view.finalPosition}
            </div>
            {view.traderPosition !== '-' && (
              <div className="mt-1 text-xs text-stone-500 dark:text-slate-400">单股原始 {view.traderPosition}</div>
            )}
          </div>
        </div>
        <div className={INSET}>
          <div className="p-3">
            <div className={LABEL}>约束状态</div>
            <div className="mt-2 text-sm text-stone-700 dark:text-slate-300">
              {view.constrainedLabel}
            </div>
            <div className="mt-1 text-xs text-stone-500 dark:text-slate-400">
              约束 {view.constraintCount} · 冲突 {view.conflictCount}
            </div>
          </div>
        </div>
        <div className={INSET}>
          <div className="p-3">
            <div className={LABEL}>深度研究</div>
            <div className="mt-2 text-sm text-stone-700 dark:text-slate-300">
              {view.deepResearchCount ? `${view.deepResearchCount} 条研究索引` : '暂无深度研究索引'}
            </div>
            {view.firstDeepResearchSummary && (
              <div className="mt-1 line-clamp-2 text-xs text-stone-500 dark:text-slate-400">{view.firstDeepResearchSummary}</div>
            )}
          </div>
        </div>
      </div>
      {(conflicts.length > 0 || constraints.length > 0) && (
        <div className="space-y-2 border-t border-stone-300/80 p-4 dark:border-slate-700">
          {conflicts.slice(0, 3).map((item, index) => (
            <div key={`conflict-${index}`} className={`rounded-sm border px-3 py-2 text-sm ${conflictTone(item.severity)}`}>
              {item.summary || item.type}
            </div>
          ))}
          {!conflicts.length && constraints.slice(0, 3).map((item, index) => (
            <div key={`constraint-${index}`} className="rounded-sm border border-stone-300 bg-[#f3eddc] px-3 py-2 text-sm text-stone-700 dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-300">
              {item.summary || item.label || item.type}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function LongTermPanel({ label, research, reviewing, notice, onReview }) {
  const qualityView = labelQualityView(label)
  return (
    <section className={PANEL}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-300/80 p-4 dark:border-slate-700">
        <div>
          <div className={LABEL}>长期标签 / 信号复盘</div>
          <h2 className="mt-1 text-sm font-semibold text-stone-950 dark:text-slate-100">
            长短线约束状态
          </h2>
        </div>
        <button
          type="button"
          disabled={reviewing}
          onClick={onReview}
          className="rounded-sm border border-stone-300 bg-[#f3eddc] px-3 py-1.5 text-xs font-semibold text-stone-700 hover:border-cyan-700 hover:text-cyan-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-300 dark:hover:border-cyan-400 dark:hover:text-cyan-200"
        >
          {reviewing ? '复盘中' : '复盘最新信号'}
        </button>
      </div>
      <div className="grid gap-3 p-4 md:grid-cols-[0.8fr_1fr]">
        <div className={INSET}>
          <div className="p-3">
            <div className={LABEL}>长期观点</div>
            {label ? (
              <>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className={`rounded-sm border px-2 py-1 text-xs font-semibold ${labelTone(label.label)}`}>
                    {label.label}
                  </span>
                  {qualityView && (
                    <span className={`rounded-sm border px-2 py-1 text-xs font-semibold ${qualityView.tone}`}>
                      {qualityView.text}
                    </span>
                  )}
                  <span className="font-mono text-sm font-semibold text-stone-950 dark:text-slate-100">
                    {signed(label.score, 1)}
                  </span>
                </div>
                <div className="mt-3 font-mono text-xs text-stone-500 dark:text-slate-400">
                  {label.date} · 有效至 {label.expires_at}
                </div>
                {label.quality_notes?.length > 0 && (
                  <div className="mt-2 text-xs leading-relaxed text-stone-500 dark:text-slate-400">
                    {label.quality_notes.slice(0, 2).join(' / ')}
                  </div>
                )}
              </>
            ) : (
              <div className="mt-3 text-sm text-stone-500 dark:text-slate-400">暂无有效长期标签</div>
            )}
          </div>
        </div>
        <div className={INSET}>
          <div className="p-3">
            <div className={LABEL}>关键发现</div>
            <div className="mt-2 space-y-2">
              {(label?.key_findings?.length ? label.key_findings : ['等待长期分析师团生成后补充。']).slice(0, 3).map((item, index) => (
                <div key={index} className="text-sm leading-relaxed text-stone-700 dark:text-slate-300">
                  {item}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      {(notice || research?.last_review?.attribution?.length > 0) && (
        <div className="border-t border-stone-300/80 px-4 py-3 text-xs leading-relaxed text-stone-500 dark:border-slate-700 dark:text-slate-400">
          {notice || `最近复盘：${research.last_review.attribution.join(' / ')}`}
        </div>
      )}
    </section>
  )
}

function SignalHistoryPanel({ signals }) {
  return (
    <section className={PANEL}>
      <div className="border-b border-stone-300/80 p-4 dark:border-slate-700">
        <div className={LABEL}>历史信号</div>
        <h2 className="mt-1 text-sm font-semibold text-stone-950 dark:text-slate-100">最近记录</h2>
      </div>
      <div className="divide-y divide-stone-300/80 dark:divide-slate-700">
        {(signals || []).slice(0, 8).map((item) => (
          <div key={`${item.date}-${item.id}`} className="grid grid-cols-[86px_1fr_auto] items-center gap-3 px-4 py-3 text-sm">
            <span className="font-mono text-xs text-stone-500 dark:text-slate-400">{item.date}</span>
            <span className="truncate text-stone-950 dark:text-slate-100">{item.recommendation}</span>
            <span className="font-mono font-semibold text-stone-700 dark:text-slate-200">{signed(item.composite_score, 1)}</span>
          </div>
        ))}
        {!signals?.length && (
          <div className="px-4 py-6 text-sm text-stone-500 dark:text-slate-400">暂无历史信号</div>
        )}
      </div>
    </section>
  )
}

function SectionNotice({ status, label }) {
  if (status?.loading) {
    return (
      <div className="rounded-sm border border-stone-300/80 bg-[#faf6ec] px-3 py-2 text-xs text-stone-500 dark:border-slate-700 dark:bg-[#1d232e] dark:text-slate-400">
        {label}加载中…
      </div>
    )
  }
  if (status?.error) {
    return (
      <div className="rounded-sm border border-amber-500/35 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-200">
        {label}暂不可用：{status.error}
      </div>
    )
  }
  return null
}

export default function StockDetailPage({ theme = 'dark' }) {
  const { symbol } = useParams()
  const [signal, setSignal] = useState(null)
  const [dossier, setDossier] = useState(null)
  const [prices, setPrices] = useState([])
  const [news, setNews] = useState(null)
  const [evalData, setEvalData] = useState(null)
  const [evidence, setEvidence] = useState([])
  const [research, setResearch] = useState(null)
  const [coverage, setCoverage] = useState(null)
  const [longTerm, setLongTerm] = useState(null)
  const [history, setHistory] = useState([])
  const [evalDays, setEvalDays] = useState(60)
  const [evalLoading, setEvalLoading] = useState(true)
  const [reviewing, setReviewing] = useState(false)
  const [copilotLoading, setCopilotLoading] = useState(false)
  const [copilotError, setCopilotError] = useState('')
  const [coreLoading, setCoreLoading] = useState(true)
  const [coreError, setCoreError] = useState('')
  const [sectionStatus, setSectionStatus] = useState(createSecondaryLoadingStatus)
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let cancelled = false
    const settleSection = (name, patch) => {
      if (!cancelled) setSectionStatus((prev) => markStockDetailSection(prev, name, patch))
    }
    const loadSection = (name, request, applyData) => {
      settleSection(name, { loading: true, error: '' })
      request
        .then((data) => {
          if (!cancelled) applyData(data)
        })
        .catch((e) => {
          settleSection(name, { error: e.message || '加载失败' })
        })
        .finally(() => {
          settleSection(name, { loading: false })
        })
    }

    setCoreLoading(true)
    setCoreError('')
    setSectionStatus(createSecondaryLoadingStatus())
    setSignal(null)
    setDossier(null)
    setPrices([])
    setNews(null)
    setEvalData(null)
    setEvidence([])
    setResearch(null)
    setCoverage(null)
    setLongTerm(null)
    setHistory([])

    Promise.allSettled([
      getLatestSignal(symbol),
      getPrices(symbol, 120),
    ]).then(([sig, px]) => {
      if (cancelled) return
      const failures = []
      if (sig.status === 'fulfilled') setSignal(sig.value)
      else failures.push('最新信号')
      if (px.status === 'fulfilled') setPrices(px.value)
      else failures.push('价格主图')
      setCoreError(failures.length ? `${failures.join('、')}加载失败` : '')
    }).finally(() => {
      if (!cancelled) setCoreLoading(false)
    })

    loadSection('dossier', getResearchDossier(symbol), (ds) => {
      setDossier(ds)
      if (ds?.latest_signal) setSignal(ds.latest_signal)
      if (ds?.evidence) setEvidence(ds.evidence)
      if (ds?.research_state) setResearch(ds.research_state)
      if (ds?.long_term_label) setLongTerm(ds.long_term_label)
    })
    loadSection('news', getNews(symbol, 48), setNews)
    loadSection('evidence', getSignalEvidence(symbol, 5), setEvidence)
    loadSection('research', getResearchState(symbol), setResearch)
    loadSection('coverage', getDataCoverage(), setCoverage)
    loadSection('longTerm', getLongTermLabel(symbol), setLongTerm)
    loadSection('history', getSignals(symbol, 8), setHistory)

    return () => {
      cancelled = true
    }
  }, [symbol])

  useEffect(() => {
    setEvalLoading(true)
    getSignalEval(symbol, evalDays)
      .then((data) => setEvalData(data))
      .catch(() => setEvalData(null))
      .finally(() => setEvalLoading(false))
  }, [symbol, evalDays])

  async function handleReviewLatest() {
    setReviewing(true)
    setNotice('')
    try {
      await reviewLatestSignal(symbol)
      const [nextResearch, nextEvidence] = await Promise.all([
        getResearchState(symbol).catch(() => null),
        getSignalEvidence(symbol, 5).catch(() => []),
      ])
      setResearch(nextResearch)
      setEvidence(nextEvidence)
      setNotice('最新信号复盘已完成')
    } catch (e) {
      setNotice(e.message)
    } finally {
      setReviewing(false)
    }
  }

  async function handleRefreshCopilot() {
    setCopilotLoading(true)
    setCopilotError('')
    try {
      const card = await refreshResearchCopilot(symbol)
      setResearch((prev) => ({ ...(prev || { symbol }), copilot: card }))
    } catch (e) {
      setCopilotError(e.message || '副驾驶生成失败')
    } finally {
      setCopilotLoading(false)
    }
  }

  return (
    <div>
      <div className="mb-5 rounded-sm border border-stone-300/80 bg-[#faf6ec] p-5 dark:border-slate-700 dark:bg-[#1d232e]">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 text-xs text-stone-500 dark:text-slate-400">
              <Link to="/" className="hover:text-cyan-700 dark:hover:text-cyan-300">
                ← 脉冲驾驶舱
              </Link>
              <span>/</span>
              <span>个股详情</span>
            </div>
            <div className="mt-3 flex flex-wrap items-baseline gap-3">
              <h1 className="text-4xl font-semibold tracking-tight text-stone-950 dark:text-slate-50">{symbol}</h1>
              {signal?.recommendation && (
                <span className="rounded-sm border border-cyan-600/30 bg-cyan-600/10 px-2.5 py-1 text-xs font-semibold text-cyan-700 dark:text-cyan-200">
                  {signal.recommendation}
                </span>
              )}
            </div>
            <div className="mt-2 text-sm text-stone-500 dark:text-slate-400">
              决策证据 · 回测复盘 · 新闻情绪
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2 text-right">
            <div className="rounded-sm border border-stone-300 bg-[#f3eddc] px-3 py-2 dark:border-slate-700 dark:bg-[#161b25]">
              <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-stone-500 dark:text-slate-400">综合分</div>
              <div className="mt-1 font-mono text-lg text-stone-950 dark:text-slate-100">
                {signal ? `${signal.composite_score > 0 ? '+' : ''}${signal.composite_score.toFixed(1)}` : '-'}
              </div>
            </div>
            <div className="rounded-sm border border-stone-300 bg-[#f3eddc] px-3 py-2 dark:border-slate-700 dark:bg-[#161b25]">
              <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-stone-500 dark:text-slate-400">止损</div>
              <div className="mt-1 font-mono text-lg text-emerald-700 dark:text-emerald-200">
                {signal?.stop_loss ? signal.stop_loss.toFixed(2) : '-'}
              </div>
            </div>
            <div className="rounded-sm border border-stone-300 bg-[#f3eddc] px-3 py-2 dark:border-slate-700 dark:bg-[#161b25]">
              <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-stone-500 dark:text-slate-400">止盈</div>
              <div className="mt-1 font-mono text-lg text-red-700 dark:text-red-200">
                {signal?.take_profit ? signal.take_profit.toFixed(2) : '-'}
              </div>
            </div>
          </div>
        </div>
      </div>

        <div className="space-y-4">
          {coreError && (
            <div className="rounded-sm border border-amber-500/35 bg-amber-500/10 px-4 py-3 text-sm text-amber-700 dark:text-amber-200">
              {coreError}
            </div>
          )}
          {/* 主图 */}
          {coreLoading ? (
            <div className="rounded-sm border border-stone-300/80 bg-[#faf6ec] py-20 text-center text-sm text-stone-500 dark:border-slate-700 dark:bg-[#1d232e] dark:text-slate-400">
              加载主图和最新信号…
            </div>
          ) : (
            <Chart prices={prices} signal={signal} theme={theme} />
          )}

          {hasSecondaryLoading(sectionStatus) && (
            <div className="rounded-sm border border-stone-300/80 bg-[#faf6ec] px-4 py-3 text-sm text-stone-500 dark:border-slate-700 dark:bg-[#1d232e] dark:text-slate-400">
              正在补充新闻、证据和长期标签...
            </div>
          )}

          {/* 信号卡片 + 新闻侧栏 */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-2 space-y-4">
              <SectionNotice status={sectionStatus.longTerm} label="长期标签" />
              <SectionNotice status={sectionStatus.research} label="研究状态" />
              <LongTermPanel
                label={longTerm}
                research={research}
                reviewing={reviewing}
                notice={notice}
                onReview={handleReviewLatest}
              />
              <SectionNotice status={sectionStatus.dossier} label="研究档案" />
              <DossierPanel dossier={dossier} signal={signal} />
              <SignalCard signal={signal} />
              <ResearchCopilotCard
                copilot={research?.copilot}
                loading={copilotLoading}
                error={copilotError}
                onRefresh={handleRefreshCopilot}
              />
              <SectionNotice status={sectionStatus.evidence} label="证据链" />
              <SectionNotice status={sectionStatus.coverage} label="数据覆盖" />
              <EvidenceCard evidence={evidence} research={research} coverage={coverage} />
              <SignalEvalCard
                evalData={evalData}
                days={evalDays}
                onDaysChange={setEvalDays}
                loading={evalLoading}
              />
              <SectionNotice status={sectionStatus.history} label="历史信号" />
              <SignalHistoryPanel signals={history} />
            </div>
            <div>
              <SectionNotice status={sectionStatus.news} label="新闻" />
              <NewsSidebar news={sectionStatus.news?.error ? [] : news} />
            </div>
          </div>
        </div>
    </div>
  )
}
