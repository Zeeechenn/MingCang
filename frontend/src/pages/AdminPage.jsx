import { useEffect, useState } from 'react'
import {
  getDashboardSummary,
  getDataCoverage,
  getModelStatus,
  getRuntimeConfig,
  getSystemHealth,
  getSystemStatus,
  resetKillSwitch,
  runDeepResearch,
  trainModel,
  triggerKillSwitch,
  triggerLongTermTeam,
  updateRuntimeConfig,
} from '../api'

const PANEL = 'rounded-sm border border-stone-300 bg-[#faf6ec] dark:border-slate-700 dark:bg-[#1d232e]'
const INSET = 'rounded-sm border border-stone-300 bg-[#f3eddc] dark:border-slate-700 dark:bg-[#161b25]'
const LABEL = 'text-[10px] font-semibold uppercase tracking-[0.2em] text-stone-500 dark:text-slate-400'

const SECTIONS = [
  ['decision', '决策引擎', '阈值 / 权重'],
  ['portfolio', '组合规则', '仓位 / 出场'],
  ['agents', 'LLM 与 Agent', '辩论 / 记忆'],
  ['data', '数据源', '价格 / 新闻'],
  ['schedule', '调度', 'A 股日历'],
  ['risk', '熔断开关', '风控保护'],
]

const SECTION_COPY = {
  decision: ['01 · 决策引擎', '规则草稿', '控制综合分如何计算，以及哪些信号可以进入可小仓试错。'],
  portfolio: ['02 · 组合规则', '仓位草稿', '集中展示纸面交易仓位、止损止盈和退出保护的后端参数。'],
  agents: ['03 · LLM 与 Agent', '辩论草稿', '控制多空辩论、仲裁置信度和记忆读取边界。'],
  data: ['04 · 数据源', '数据草稿', '检查价格、财报、新闻覆盖率，并保留本地优先的数据源策略。'],
  schedule: ['05 · 调度', '日历草稿', '展示 A 股交易日相关的盘前、盘后、止损检查调度入口。'],
  risk: ['06 · 熔断开关', '风控草稿', '集中管理会阻断调度或跳过交易建议的保护性开关。'],
}

function SettingRow({ label, hint, children, danger = false }) {
  return (
    <div className="grid gap-4 border-b border-stone-300 py-4 last:border-b-0 dark:border-slate-700 md:grid-cols-[1fr_auto] md:items-center">
      <div>
        <div className={`text-sm font-medium ${danger ? 'text-emerald-700 dark:text-emerald-200' : 'text-stone-950 dark:text-slate-100'}`}>
          {label}
        </div>
        <div className="mt-1 text-xs leading-relaxed text-stone-500 dark:text-slate-400">{hint}</div>
      </div>
      <div className="flex justify-start md:justify-end">{children}</div>
    </div>
  )
}

function Toggle({ value, onChange, danger = false }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!value)}
      className={`relative h-6 w-12 rounded-full border transition-colors ${
        value
          ? danger
            ? 'border-emerald-600 bg-emerald-600'
            : 'border-cyan-700 bg-cyan-700'
          : 'border-stone-300 bg-[#efe9dc] dark:border-slate-700 dark:bg-slate-900'
      }`}
    >
      <span
        className={`absolute top-0.5 h-4 w-4 rounded-full bg-[#faf6ec] transition-transform dark:bg-slate-100 ${
          value ? 'translate-x-6' : 'translate-x-1'
        }`}
      />
    </button>
  )
}

function ActionButton({ children, onClick, disabled = false, danger = false, type = 'button' }) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rounded-sm border px-3 py-1.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50 ${
        danger
          ? 'border-emerald-600/40 bg-emerald-600/10 text-emerald-700 hover:border-emerald-700 dark:text-emerald-200 dark:hover:border-emerald-300'
          : 'border-stone-300 bg-[#f3eddc] text-stone-700 hover:border-cyan-700 hover:text-cyan-700 dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-300 dark:hover:border-cyan-400 dark:hover:text-cyan-200'
      }`}
    >
      {children}
    </button>
  )
}

function Slider({ value, min, max, onChange, suffix = '' }) {
  const pct = ((value - min) / (max - min)) * 100
  return (
    <div className="flex min-w-[260px] items-center gap-4">
      <div className="relative h-5 flex-1">
        <div className="absolute left-0 right-0 top-2 h-1 rounded bg-stone-300 dark:bg-slate-800" />
        <div className="absolute left-0 top-2 h-1 rounded bg-cyan-700 dark:bg-cyan-400" style={{ width: `${pct}%` }} />
        <input
          type="range"
          min={min}
          max={max}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="absolute inset-0 h-5 w-full cursor-pointer opacity-0"
        />
      </div>
      <span className="min-w-12 text-right font-mono text-sm font-semibold text-stone-950 dark:text-slate-100">
        {value}{suffix}
      </span>
    </div>
  )
}

function Segmented({ value, options, onChange }) {
  return (
    <div className="inline-flex overflow-hidden rounded-sm border border-stone-300 dark:border-slate-700">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => onChange(option)}
          className={`border-l border-stone-300 px-3 py-1.5 text-xs font-semibold first:border-l-0 dark:border-slate-700 ${
            value === option
              ? 'bg-cyan-700 text-white dark:bg-cyan-400 dark:text-slate-950'
              : 'bg-transparent text-stone-500 dark:text-slate-400'
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  )
}

function Weights({ weights }) {
  const rows = [
    ['量化', weights.quant, 'bg-cyan-700 dark:bg-cyan-400'],
    ['技术', weights.technical, 'bg-red-600'],
    ['情感', weights.sentiment, 'bg-amber-600'],
  ]
  return (
    <div className="w-[320px]">
      <div className="flex h-2 overflow-hidden rounded bg-stone-300 dark:bg-slate-800">
        {rows.map(([label, value, cls]) => (
          <div key={label} className={cls} style={{ width: `${value * 100}%` }} />
        ))}
      </div>
      <div className="mt-3 grid grid-cols-3 gap-3">
        {rows.map(([label, value, cls]) => (
          <div key={label}>
            <div className="flex items-center gap-1.5 text-xs text-stone-500 dark:text-slate-400">
              <span className={`h-2 w-2 rounded-sm ${cls}`} />
              {label}
            </div>
            <div className="mt-1 font-mono text-sm font-semibold text-stone-950 dark:text-slate-100">
              {(value * 100).toFixed(0)}%
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

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
  const [trailingStop, setTrailingStop] = useState(false)
  const [killSwitch, setKillSwitch] = useState(false)
  const [saving, setSaving] = useState(false)
  const [actionBusy, setActionBusy] = useState('')
  const [message, setMessage] = useState('')
  const [deepTopic, setDeepTopic] = useState('')
  const [deepSymbols, setDeepSymbols] = useState('')
  const [deepResult, setDeepResult] = useState(null)

  async function loadAdmin() {
    Promise.all([
      getDashboardSummary().catch(() => null),
      getDataCoverage().catch(() => null),
      getRuntimeConfig().catch(() => null),
      getSystemStatus().catch(() => null),
      getSystemHealth().catch(() => null),
      getModelStatus().catch(() => null),
    ]).then(([dashboard, dataCoverage, runtimeConfig, status, healthData, model]) => {
      setSummary(dashboard)
      setCoverage(dataCoverage)
      setRuntime(runtimeConfig)
      setSystemStatus(status)
      setHealth(healthData)
      setModelStatus(model)
      if (runtimeConfig?.profile) setProfile(runtimeConfig.profile)
      if (runtimeConfig?.new_framework_entry_threshold) setThreshold(Math.round(runtimeConfig.new_framework_entry_threshold))
      if (runtimeConfig?.director_min_confidence !== undefined) setConfidence(Math.round(runtimeConfig.director_min_confidence * 100))
      if (runtimeConfig?.regime_filter_enabled !== undefined) setLimitGuard(Boolean(runtimeConfig.regime_filter_enabled))
      if (runtimeConfig?.adx_filter_enabled !== undefined) setAdxFilter(Boolean(runtimeConfig.adx_filter_enabled))
      if (runtimeConfig?.multi_agent_enabled !== undefined) setMultiAgent(Boolean(runtimeConfig.multi_agent_enabled))
      if (runtimeConfig?.risk_manager_enabled !== undefined) setRiskManager(Boolean(runtimeConfig.risk_manager_enabled))
      if (runtimeConfig?.long_term_team_enabled !== undefined) setLongTermTeam(Boolean(runtimeConfig.long_term_team_enabled))
      if (runtimeConfig?.trailing_stop_enabled !== undefined) setTrailingStop(Boolean(runtimeConfig.trailing_stop_enabled))
      setKillSwitch(Boolean(healthData?.kill_switch?.active || dashboard?.system?.kill_switch?.active))
    })
  }

  useEffect(() => {
    loadAdmin()
  }, [])

  const weights = summary?.system?.weights || { quant: 0, technical: 0.6, sentiment: 0.4 }
  const cov = coverage?.summary || summary?.coverage?.summary || {}
  const [sectionEyebrow, sectionTitle, sectionDescription] = SECTION_COPY[active] || SECTION_COPY.decision

  async function handleSaveRuntime() {
    setSaving(true)
    setMessage('')
    try {
      const updated = await updateRuntimeConfig({
        paper_trading_profile: profile,
        new_framework_entry_threshold: threshold,
        director_min_confidence: confidence / 100,
        regime_filter_enabled: limitGuard,
        adx_filter_enabled: adxFilter,
        multi_agent_enabled: multiAgent,
        risk_manager_enabled: riskManager,
        long_term_team_enabled: longTermTeam,
        trailing_stop_enabled: trailingStop,
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

  async function runAction(key, fn, successText) {
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
            <span className="rounded-sm border border-stone-300 px-2 py-1 dark:border-slate-700">v0.1.0</span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              本地配置
            </span>
          </div>
        </div>

        <div className="grid gap-4 p-4 lg:grid-cols-[230px_minmax(0,1fr)_320px]">
          <nav className={PANEL}>
            <div className="border-b border-stone-300 p-4 dark:border-slate-700">
              <div className={LABEL}>配置分区</div>
            </div>
            <div className="p-2">
              {SECTIONS.map(([id, label, hint]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setActive(id)}
                  className={`grid w-full grid-cols-[8px_1fr] gap-3 rounded-sm px-3 py-3 text-left ${
                    active === id ? 'bg-[#f3eddc] dark:bg-[#161b25]' : 'hover:bg-[#f3eddc] dark:hover:bg-[#161b25]'
                  }`}
                >
                  <span className={`mt-1.5 h-1.5 w-1.5 rounded-full ${id === 'risk' ? 'bg-emerald-600' : active === id ? 'bg-cyan-700 dark:bg-cyan-400' : 'bg-stone-400 dark:bg-slate-600'}`} />
                  <span>
                    <span className="block text-sm font-medium text-stone-950 dark:text-slate-100">{label}</span>
                    <span className="mt-0.5 block text-xs text-stone-500 dark:text-slate-400">{hint}</span>
                  </span>
                </button>
              ))}
            </div>
          </nav>

          <section className={PANEL}>
            <div className="border-b border-stone-300 p-5 dark:border-slate-700">
              <div className={LABEL}>{sectionEyebrow}</div>
              <h2 className="mt-1 text-xl font-semibold text-stone-950 dark:text-slate-50">{sectionTitle}</h2>
              <p className="mt-2 text-sm italic text-stone-500 dark:text-slate-400">
                {sectionDescription}
              </p>
            </div>
            <div className="px-5">
              <SettingRow label="系统 profile" hint="选择当前规则包。切换后下一次调度会按新 profile 重新生成信号。">
                <Segmented value={profile} onChange={setProfile} options={['auto', 'test1_legacy_qlib', 'new_framework']} />
              </SettingRow>
              <SettingRow label="入场阈值" hint="综合分超过该阈值才进入入场候选。数值越高越严格。">
                <Slider value={threshold} min={0} max={45} onChange={setThreshold} />
              </SettingRow>
              <SettingRow label="Director 置信度地板" hint="平均置信度低于该值时，Research Director 会标记数据不足。">
                <Slider value={confidence} min={0} max={100} onChange={setConfidence} suffix="%" />
              </SettingRow>
              <SettingRow label="综合分权重" hint="量化 / 技术 / 情感三路信号的当前权重。">
                <Weights weights={weights} />
              </SettingRow>
              <SettingRow label="大盘择时过滤" hint="启用后，盘后信号会用 RSRS 与板块扩散对强信号做衰减。">
                <Toggle value={limitGuard} onChange={setLimitGuard} />
              </SettingRow>
              <SettingRow label="ADX 震荡过滤" hint="启用后，技术分在震荡市按 ADX 系数衰减。">
                <Toggle value={adxFilter} onChange={setAdxFilter} />
              </SettingRow>
              <SettingRow label="多 Agent 决策" hint="控制盘后是否走 Analyst → Director → Researcher → Trader → RiskManager。">
                <Toggle value={multiAgent} onChange={setMultiAgent} />
              </SettingRow>
              <SettingRow label="风险经理" hint="启用后，RiskManager 可根据大盘、涨跌停、长期标签否决或降级信号。">
                <Toggle value={riskManager} onChange={setRiskManager} danger />
              </SettingRow>
              <SettingRow label="长期分析师团" hint="控制周频长期标签，以及长期标签对短线信号的约束。">
                <Toggle value={longTermTeam} onChange={setLongTermTeam} />
              </SettingRow>
              <SettingRow label="移动止损" hint="启用后，持仓跟踪模块可按 ATR trailing stop 更新动态止损。">
                <Toggle value={trailingStop} onChange={setTrailingStop} />
              </SettingRow>
              <SettingRow label="保存运行时配置" hint="只影响当前后端进程；重启后仍以 .env 为准。">
                <ActionButton onClick={handleSaveRuntime} disabled={saving}>
                  {saving ? '保存中' : '应用'}
                </ActionButton>
              </SettingRow>
              <SettingRow label="熔断状态" hint="触发后跳过盘前、盘后、止损检查调度；重置需要明确操作。" danger>
                <span className={`rounded-sm border px-2 py-1 text-xs font-semibold ${
                  killSwitch
                    ? 'border-emerald-600/40 bg-emerald-600/10 text-emerald-700 dark:text-emerald-200'
                    : 'border-cyan-600/30 bg-cyan-600/10 text-cyan-700 dark:text-cyan-200'
                }`}>
                  {killSwitch ? '已触发' : '正常'}
                </span>
              </SettingRow>
            </div>
          </section>

          <aside className="space-y-4">
            <section className={PANEL}>
              <div className="border-b border-stone-300 p-4 dark:border-slate-700">
                <div className={LABEL}>草稿差异</div>
                <div className="mt-1 text-sm italic text-stone-950 dark:text-slate-100">草稿 vs 当前运行</div>
              </div>
              <div className="space-y-3 p-4">
                <DiffRow path="decision.entry_threshold" before={summary?.system?.entry_threshold ?? '-'} after={threshold} />
                <DiffRow path="decision.profile" before={summary?.system?.profile ?? '-'} after={profile} />
                <DiffRow path="risk.manager" before={runtime?.risk_manager_enabled ? 'on' : 'off'} after={riskManager ? 'on' : 'off'} />
                {message && (
                  <div className="rounded-sm border border-cyan-700/30 bg-cyan-700/10 p-2 text-xs leading-relaxed text-cyan-800 dark:text-cyan-200">
                    {message}
                  </div>
                )}
              </div>
            </section>

            <section className={PANEL}>
              <div className="border-b border-stone-300 p-4 dark:border-slate-700">
                <div className={LABEL}>数据状态</div>
                <div className="mt-1 text-sm italic text-stone-950 dark:text-slate-100">覆盖与新鲜度</div>
              </div>
              <div className="grid grid-cols-2 gap-2 p-4">
                <MiniStat label="活跃标的" value={cov.active_stocks ?? '-'} />
                <MiniStat label="价格覆盖" value={cov.price_covered ?? '-'} />
                <MiniStat label="2年价格" value={cov.two_year_price_covered ?? '-'} />
                <MiniStat label="24h新闻" value={cov.news_24h_covered ?? '-'} />
              </div>
              <div className="border-t border-stone-300 px-4 py-3 text-xs leading-relaxed text-stone-500 dark:border-slate-700 dark:text-slate-400">
                最新价格 {systemStatus?.latest_price_date || health?.latest_price_date || '-'} · DB {health?.db_ok === false ? '异常' : '正常'}
              </div>
            </section>

            <section className={PANEL}>
              <div className="border-b border-stone-300 p-4 dark:border-slate-700">
                <div className={LABEL}>运行操作</div>
                <div className="mt-1 text-sm italic text-stone-950 dark:text-slate-100">模型 / 长期团 / 熔断</div>
              </div>
              <div className="space-y-3 p-4">
                <MiniStat label="模型" value={modelStatus?.exists ? '已训练' : '未训练'} />
                {modelStatus?.updated_at && (
                  <div className="font-mono text-xs text-stone-500 dark:text-slate-400">{modelStatus.updated_at}</div>
                )}
                <div className="flex flex-wrap gap-2">
                  <ActionButton disabled={actionBusy === 'train'} onClick={() => runAction('train', trainModel, '模型训练已提交后台任务')}>
                    训练模型
                  </ActionButton>
                  <ActionButton disabled={actionBusy === 'longterm'} onClick={() => runAction('longterm', triggerLongTermTeam, '长期分析师团已提交后台任务')}>
                    跑长期团
                  </ActionButton>
                  {killSwitch ? (
                    <ActionButton danger disabled={actionBusy === 'reset'} onClick={() => runAction('reset', resetKillSwitch, '熔断已重置')}>
                      重置熔断
                    </ActionButton>
                  ) : (
                    <ActionButton danger disabled={actionBusy === 'trigger'} onClick={() => runAction('trigger', () => triggerKillSwitch('manual from admin'), '熔断已触发')}>
                      触发熔断
                    </ActionButton>
                  )}
                </div>
              </div>
            </section>

            <section className={PANEL}>
              <div className="border-b border-stone-300 p-4 dark:border-slate-700">
                <div className={LABEL}>专题研究</div>
                <div className="mt-1 text-sm italic text-stone-950 dark:text-slate-100">手动深度研究</div>
              </div>
              <form onSubmit={handleDeepResearch} className="space-y-3 p-4">
                <input
                  value={deepTopic}
                  onChange={(e) => setDeepTopic(e.target.value)}
                  placeholder="主题，例如 AI算力产业链"
                  className="w-full rounded-sm border border-stone-300 bg-[#fffaf0] px-3 py-2 text-xs outline-none focus:border-cyan-700 dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-100 dark:focus:border-cyan-400"
                />
                <input
                  value={deepSymbols}
                  onChange={(e) => setDeepSymbols(e.target.value)}
                  placeholder="代码，逗号分隔"
                  className="w-full rounded-sm border border-stone-300 bg-[#fffaf0] px-3 py-2 text-xs outline-none focus:border-cyan-700 dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-100 dark:focus:border-cyan-400"
                />
                <ActionButton type="submit" disabled={actionBusy === 'deep'}>
                  {actionBusy === 'deep' ? '生成中' : '生成报告'}
                </ActionButton>
                {deepResult?.report_path && (
                  <div className="rounded-sm border border-stone-300 bg-[#f3eddc] p-2 text-xs leading-relaxed text-stone-600 dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-300">
                    {deepResult.summary}
                  </div>
                )}
              </form>
            </section>

            <section className={PANEL}>
              <div className="border-b border-stone-300 p-4 dark:border-slate-700">
                <div className={LABEL}>审计日志</div>
              </div>
              <div className="space-y-3 p-4">
                {[
                  ['当前', '读取配置快照'],
                  ['05-16', 'M6.1 数据覆盖完成'],
                  ['05-16', 'M4.9 exit 实验完成'],
                  ['05-15', '测试 1 信号更新'],
                ].map(([time, text]) => (
                  <div key={`${time}-${text}`} className="grid grid-cols-[52px_1fr] gap-3 border-b border-stone-300 pb-3 text-sm last:border-0 last:pb-0 dark:border-slate-700">
                    <span className="font-mono text-xs text-stone-500 dark:text-slate-400">{time}</span>
                    <span className="text-stone-950 dark:text-slate-100">{text}</span>
                  </div>
                ))}
              </div>
            </section>
          </aside>
        </div>
      </div>
    </div>
  )
}

function DiffRow({ path, before, after }) {
  return (
    <div>
      <div className="font-mono text-[11px] text-stone-500 dark:text-slate-400">{path}</div>
      <div className="mt-1 flex items-center gap-2 font-mono text-sm">
        <span className="text-stone-400 line-through decoration-emerald-600 dark:text-slate-500">{String(before)}</span>
        <span className="text-stone-500 dark:text-slate-500">→</span>
        <span className="font-semibold text-red-700 dark:text-red-200">{String(after)}</span>
      </div>
    </div>
  )
}

function MiniStat({ label, value }) {
  return (
    <div className={INSET}>
      <div className="p-3">
        <div className={LABEL}>{label}</div>
        <div className="mt-1 font-mono text-xl font-semibold text-stone-950 dark:text-slate-100">{value}</div>
      </div>
    </div>
  )
}
