import { useEffect, useState } from 'react'
import {
  getDashboardSummary,
  getDataCoverage,
  getInitializeStatus,
  getLLMUsage,
  getModelStatus,
  getRuntimeConfig,
  getSystemHealth,
  getSystemStatus,
  resetKillSwitch,
  runDeepResearch,
  startInitialize,
  trainModel,
  triggerKillSwitch,
  triggerLongTermTeam,
  updateRuntimeConfig,
} from '../api'
import { LABEL, PANEL } from './adminPageConstants'
import { AdminSettingsPanel, AdminSidebarCards } from './adminPagePanels'

export default function AdminPage() {
  const [summary, setSummary] = useState(null)
  const [coverage, setCoverage] = useState(null)
  const [runtime, setRuntime] = useState(null)
  const [systemStatus, setSystemStatus] = useState(null)
  const [health, setHealth] = useState(null)
  const [modelStatus, setModelStatus] = useState(null)
  const [active, setActive] = useState('decision')
  const [profile, setProfile] = useState('new_framework')
  const [threshold, setThreshold] = useState(25)
  const [confidence, setConfidence] = useState(60)
  const [limitGuard, setLimitGuard] = useState(true)
  const [adxFilter, setAdxFilter] = useState(false)
  const [multiAgent, setMultiAgent] = useState(true)
  const [riskManager, setRiskManager] = useState(true)
  const [longTermTeam, setLongTermTeam] = useState(true)
  const [longTermConstraints, setLongTermConstraints] = useState(false)
  const [trailingStop, setTrailingStop] = useState(false)
  const [weightQuant, setWeightQuant] = useState(0)
  const [weightTechnical, setWeightTechnical] = useState(60)
  const [weightSentiment, setWeightSentiment] = useState(40)
  const [maxStockPct, setMaxStockPct] = useState(15)
  const [maxSectorPct, setMaxSectorPct] = useState(30)
  const [maxTotalPct, setMaxTotalPct] = useState(80)
  const [financialYears, setFinancialYears] = useState(5)
  const [tavilyThreshold, setTavilyThreshold] = useState(3)
  const [anspireDays, setAnspireDays] = useState(2)
  const [anspireMaxResults, setAnspireMaxResults] = useState(5)
  const [anspireMaxAdd, setAnspireMaxAdd] = useState(2)
  const [anspireMinScore, setAnspireMinScore] = useState(75)
  const [dailyReviewTime, setDailyReviewTime] = useState('15:00')
  const [longtermMondayDow, setLongtermMondayDow] = useState('mon')
  const [longtermMondayTime, setLongtermMondayTime] = useState('09:00')
  const [longtermFridayDow, setLongtermFridayDow] = useState('fri')
  const [longtermFridayTime, setLongtermFridayTime] = useState('15:00')
  const [killSwitch, setKillSwitch] = useState(false)
  const [saving, setSaving] = useState(false)
  const [actionBusy, setActionBusy] = useState('')
  const [message, setMessage] = useState('')
  const [deepTopic, setDeepTopic] = useState('')
  const [deepSymbols, setDeepSymbols] = useState('')
  const [deepResult, setDeepResult] = useState(null)
  const [initStatus, setInitStatus] = useState(null)
  const initPollingRef = useState(null)
  const [llmUsage, setLlmUsage] = useState(null)

  async function loadAdmin() {
    Promise.all([
      getDashboardSummary().catch(() => null),
      getDataCoverage().catch(() => null),
      getRuntimeConfig().catch(() => null),
      getSystemStatus().catch(() => null),
      getSystemHealth().catch(() => null),
      getModelStatus().catch(() => null),
      getLLMUsage(7).catch(() => null),
    ]).then(([dashboard, dataCoverage, runtimeConfig, status, healthData, model, usage]) => {
      setSummary(dashboard)
      setCoverage(dataCoverage)
      setRuntime(runtimeConfig)
      setSystemStatus(status)
      setHealth(healthData)
      setModelStatus(model)
      setLlmUsage(usage)
      if (runtimeConfig?.profile) setProfile(runtimeConfig.profile)
      if (runtimeConfig?.new_framework_entry_threshold) setThreshold(Math.round(runtimeConfig.new_framework_entry_threshold))
      if (runtimeConfig?.director_min_confidence !== undefined) setConfidence(Math.round(runtimeConfig.director_min_confidence * 100))
      if (runtimeConfig?.regime_filter_enabled !== undefined) setLimitGuard(Boolean(runtimeConfig.regime_filter_enabled))
      if (runtimeConfig?.adx_filter_enabled !== undefined) setAdxFilter(Boolean(runtimeConfig.adx_filter_enabled))
      if (runtimeConfig?.multi_agent_enabled !== undefined) setMultiAgent(Boolean(runtimeConfig.multi_agent_enabled))
      if (runtimeConfig?.risk_manager_enabled !== undefined) setRiskManager(Boolean(runtimeConfig.risk_manager_enabled))
      if (runtimeConfig?.long_term_team_enabled !== undefined) setLongTermTeam(Boolean(runtimeConfig.long_term_team_enabled))
      if (runtimeConfig?.long_term_constraints_enabled !== undefined) setLongTermConstraints(Boolean(runtimeConfig.long_term_constraints_enabled))
      if (runtimeConfig?.trailing_stop_enabled !== undefined) setTrailingStop(Boolean(runtimeConfig.trailing_stop_enabled))
      if (runtimeConfig?.raw_weights) {
        setWeightQuant(Math.round((runtimeConfig.raw_weights.weight_quant || 0) * 100))
        setWeightTechnical(Math.round((runtimeConfig.raw_weights.weight_technical || 0) * 100))
        setWeightSentiment(Math.round((runtimeConfig.raw_weights.weight_sentiment || 0) * 100))
      }
      if (runtimeConfig?.max_position_per_stock !== undefined) setMaxStockPct(Math.round(runtimeConfig.max_position_per_stock * 100))
      if (runtimeConfig?.max_position_per_sector !== undefined) setMaxSectorPct(Math.round(runtimeConfig.max_position_per_sector * 100))
      if (runtimeConfig?.max_total_equity_pct !== undefined) setMaxTotalPct(Math.round(runtimeConfig.max_total_equity_pct * 100))
      if (runtimeConfig?.data_draft) {
        setFinancialYears(runtimeConfig.data_draft.financial_backfill_years)
        setTavilyThreshold(runtimeConfig.data_draft.tavily_supplement_threshold)
        setAnspireDays(runtimeConfig.data_draft.anspire_news_days)
        setAnspireMaxResults(runtimeConfig.data_draft.anspire_news_max_results)
        setAnspireMaxAdd(runtimeConfig.data_draft.anspire_news_max_add)
        setAnspireMinScore(runtimeConfig.data_draft.anspire_news_min_score)
      }
      if (runtimeConfig?.schedule) {
        setDailyReviewTime(runtimeConfig.schedule.daily_review_time)
        setLongtermMondayDow(runtimeConfig.schedule.longterm_monday_dow || 'mon')
        setLongtermMondayTime(runtimeConfig.schedule.longterm_monday_time)
        setLongtermFridayDow(runtimeConfig.schedule.longterm_friday_dow || 'fri')
        setLongtermFridayTime(runtimeConfig.schedule.longterm_friday_time)
      }
      setKillSwitch(Boolean(healthData?.kill_switch?.active || dashboard?.system?.kill_switch?.active))
    })
  }

  useEffect(() => {
    loadAdmin()
    getInitializeStatus().then(setInitStatus).catch(() => null)
  }, [])

  function startInitPolling() {
    if (initPollingRef[0]) return
    const id = setInterval(async () => {
      try {
        const s = await getInitializeStatus()
        setInitStatus(s)
        if (!s.running && (s.step === 'done' || s.step === 'error')) {
          clearInterval(id)
          initPollingRef[0] = null
          if (s.step === 'done') loadAdmin()
        }
      } catch {}
    }, 2000)
    initPollingRef[0] = id
  }

  async function handleInitialize() {
    if (!window.confirm('立即执行冷启动初始化？这会触发行情、财报、披露日和信号生成任务。')) return
    setMessage('')
    try {
      await startInitialize()
      const s = await getInitializeStatus()
      setInitStatus(s)
      startInitPolling()
    } catch (err) {
      setMessage(err.message)
    }
  }

  async function handleSaveRuntime() {
    if (!window.confirm('应用当前运行时配置？该设置只影响当前后端进程。')) return
    setSaving(true)
    setMessage('')
    try {
      const updated = await updateRuntimeConfig({
        signal_profile: profile,
        new_framework_entry_threshold: threshold,
        director_min_confidence: confidence / 100,
        regime_filter_enabled: limitGuard,
        adx_filter_enabled: adxFilter,
        multi_agent_enabled: multiAgent,
        risk_manager_enabled: riskManager,
        long_term_team_enabled: longTermTeam,
        long_term_constraints_enabled: longTermConstraints,
        trailing_stop_enabled: trailingStop,
        weight_quant: weightQuant / 100,
        weight_technical: weightTechnical / 100,
        weight_sentiment: weightSentiment / 100,
        max_position_per_stock: maxStockPct / 100,
        max_position_per_sector: maxSectorPct / 100,
        max_total_equity_pct: maxTotalPct / 100,
        financial_backfill_years: financialYears,
        tavily_supplement_threshold: tavilyThreshold,
        anspire_news_days: anspireDays,
        anspire_news_max_results: anspireMaxResults,
        anspire_news_max_add: anspireMaxAdd,
        anspire_news_min_score: anspireMinScore,
        schedule_daily_review_time: dailyReviewTime,
        schedule_longterm_monday_dow: longtermMondayDow,
        schedule_longterm_monday_time: longtermMondayTime,
        schedule_longterm_friday_dow: longtermFridayDow,
        schedule_longterm_friday_time: longtermFridayTime,
      })
      setRuntime(updated)
      setMessage(updated.note || '运行时配置已更新')
      await loadAdmin()
    } catch (err) {
      setMessage(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function runAction(key, fn, successText, confirmText = '') {
    if (confirmText && !window.confirm(confirmText)) return
    setActionBusy(key)
    setMessage('')
    try {
      await fn()
      setMessage(successText)
      await loadAdmin()
    } catch (err) {
      setMessage(err.message)
    } finally {
      setActionBusy('')
    }
  }

  async function handleDeepResearch(e) {
    e.preventDefault()
    if (!deepTopic.trim()) return
    if (!window.confirm('立即生成专题深度研究？该操作可能调用本地或云端 LLM。')) return
    setActionBusy('deep')
    setMessage('')
    setDeepResult(null)
    try {
      const result = await runDeepResearch({
        topic: deepTopic.trim(),
        symbols: deepSymbols.split(',').map((s) => s.trim()).filter(Boolean),
      })
      setDeepResult(result)
      setMessage('专题研究已生成')
      await loadAdmin()
    } catch (err) {
      setMessage(err.message)
    } finally {
      setActionBusy('')
    }
  }

  function handleRunLongTermTeam() {
    return runAction('longterm', triggerLongTermTeam, '长期分析师团已提交后台任务', '立即运行长期分析师团？')
  }

  function handleTrainModel() {
    return runAction('train', trainModel, '模型训练已提交后台任务', '立即提交模型训练任务？')
  }

  function handleResetKillSwitch() {
    return runAction('reset', resetKillSwitch, '熔断已重置', '确认重置熔断状态？')
  }

  function handleTriggerKillSwitch() {
    return runAction('trigger', () => triggerKillSwitch('manual from admin'), '熔断已触发', '确认手动触发熔断？')
  }

  const weights = summary?.system?.weights || { quant: 0, technical: 0.6, sentiment: 0.4 }
  const draftWeights = {
    quant: weightQuant / 100,
    technical: weightTechnical / 100,
    sentiment: weightSentiment / 100,
  }
  const weightTotal = weightQuant + weightTechnical + weightSentiment
  const cov = coverage?.summary || summary?.coverage?.summary || {}

  return (
    <div className="space-y-4">
      <div className={PANEL}>
        <div className="flex flex-wrap items-end justify-between gap-4 border-b border-stone-300 p-5 dark:border-slate-700">
          <div>
            <div className={LABEL}>系统配置</div>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight text-stone-950 dark:text-slate-50">
              后端参数界面
            </h1>
            <p className="mt-2 text-sm text-stone-500 dark:text-slate-400">
              当前页面只展示与编辑草稿，不直接写入交易规则；应用前需要单独确认。
            </p>
          </div>
          <div className="flex items-center gap-3 font-mono text-xs text-stone-500 dark:text-slate-400">
            <span className="rounded-sm border border-stone-300 px-2 py-1 dark:border-slate-700">v0.2.0</span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              本地配置
            </span>
          </div>
        </div>

        <div className="grid gap-4 p-4 lg:grid-cols-[230px_minmax(0,1fr)_320px]">
          <AdminSettingsPanel
            active={active}
            setActive={setActive}
            profile={profile}
            setProfile={setProfile}
            threshold={threshold}
            setThreshold={setThreshold}
            confidence={confidence}
            setConfidence={setConfidence}
            weightQuant={weightQuant}
            setWeightQuant={setWeightQuant}
            weightTechnical={weightTechnical}
            setWeightTechnical={setWeightTechnical}
            weightSentiment={weightSentiment}
            setWeightSentiment={setWeightSentiment}
            draftWeights={draftWeights}
            weightTotal={weightTotal}
            riskManager={riskManager}
            setRiskManager={setRiskManager}
            trailingStop={trailingStop}
            setTrailingStop={setTrailingStop}
            maxStockPct={maxStockPct}
            setMaxStockPct={setMaxStockPct}
            maxSectorPct={maxSectorPct}
            setMaxSectorPct={setMaxSectorPct}
            maxTotalPct={maxTotalPct}
            setMaxTotalPct={setMaxTotalPct}
            multiAgent={multiAgent}
            setMultiAgent={setMultiAgent}
            longTermTeam={longTermTeam}
            setLongTermTeam={setLongTermTeam}
            longTermConstraints={longTermConstraints}
            setLongTermConstraints={setLongTermConstraints}
            actionBusy={actionBusy}
            onRunLongTermTeam={handleRunLongTermTeam}
            cov={cov}
            financialYears={financialYears}
            setFinancialYears={setFinancialYears}
            tavilyThreshold={tavilyThreshold}
            setTavilyThreshold={setTavilyThreshold}
            anspireDays={anspireDays}
            setAnspireDays={setAnspireDays}
            anspireMaxResults={anspireMaxResults}
            setAnspireMaxResults={setAnspireMaxResults}
            anspireMaxAdd={anspireMaxAdd}
            setAnspireMaxAdd={setAnspireMaxAdd}
            anspireMinScore={anspireMinScore}
            setAnspireMinScore={setAnspireMinScore}
            health={health}
            systemStatus={systemStatus}
            initStatus={initStatus}
            onInitialize={handleInitialize}
            dailyReviewTime={dailyReviewTime}
            setDailyReviewTime={setDailyReviewTime}
            longtermMondayDow={longtermMondayDow}
            setLongtermMondayDow={setLongtermMondayDow}
            longtermMondayTime={longtermMondayTime}
            setLongtermMondayTime={setLongtermMondayTime}
            longtermFridayDow={longtermFridayDow}
            setLongtermFridayDow={setLongtermFridayDow}
            longtermFridayTime={longtermFridayTime}
            setLongtermFridayTime={setLongtermFridayTime}
            limitGuard={limitGuard}
            setLimitGuard={setLimitGuard}
            adxFilter={adxFilter}
            setAdxFilter={setAdxFilter}
            killSwitch={killSwitch}
            llmUsage={llmUsage}
            saving={saving}
            onSaveRuntime={handleSaveRuntime}
          />
          <AdminSidebarCards
            initStatus={initStatus}
            onInitialize={handleInitialize}
            summary={summary}
            runtime={runtime}
            weights={weights}
            threshold={threshold}
            profile={profile}
            weightQuant={weightQuant}
            weightTechnical={weightTechnical}
            weightSentiment={weightSentiment}
            maxTotalPct={maxTotalPct}
            riskManager={riskManager}
            message={message}
            cov={cov}
            systemStatus={systemStatus}
            health={health}
            modelStatus={modelStatus}
            actionBusy={actionBusy}
            onTrainModel={handleTrainModel}
            onRunLongTermTeam={handleRunLongTermTeam}
            killSwitch={killSwitch}
            onResetKillSwitch={handleResetKillSwitch}
            onTriggerKillSwitch={handleTriggerKillSwitch}
            deepTopic={deepTopic}
            setDeepTopic={setDeepTopic}
            deepSymbols={deepSymbols}
            setDeepSymbols={setDeepSymbols}
            deepResult={deepResult}
            onDeepResearch={handleDeepResearch}
          />
        </div>
      </div>
    </div>
  )
}
