import { LABEL, PANEL, SECTION_COPY, SECTIONS } from './adminPageConstants'
import MemorySection from './MemorySection'
import {
  ActionButton,
  DayInput,
  DiffRow,
  InitStepBar,
  MiniStat,
  NumberInput,
  SchedulerState,
  Segmented,
  Slider,
  SettingRow,
  TimeInput,
  Toggle,
  Weights,
} from './adminPageUi'

export function AdminSettingsPanel({
  active,
  setActive,
  profile,
  setProfile,
  threshold,
  setThreshold,
  confidence,
  setConfidence,
  weightQuant,
  setWeightQuant,
  weightTechnical,
  setWeightTechnical,
  weightSentiment,
  setWeightSentiment,
  draftWeights,
  weightTotal,
  riskManager,
  setRiskManager,
  trailingStop,
  setTrailingStop,
  maxStockPct,
  setMaxStockPct,
  maxSectorPct,
  setMaxSectorPct,
  maxTotalPct,
  setMaxTotalPct,
  multiAgent,
  setMultiAgent,
  longTermTeam,
  setLongTermTeam,
  longTermConstraints,
  setLongTermConstraints,
  actionBusy,
  onRunLongTermTeam,
  cov,
  financialYears,
  setFinancialYears,
  tavilyThreshold,
  setTavilyThreshold,
  anspireDays,
  setAnspireDays,
  anspireMaxResults,
  setAnspireMaxResults,
  anspireMaxAdd,
  setAnspireMaxAdd,
  anspireMinScore,
  setAnspireMinScore,
  health,
  systemStatus,
  initStatus,
  onInitialize,
  dailyReviewTime,
  setDailyReviewTime,
  longtermMondayDow,
  setLongtermMondayDow,
  longtermMondayTime,
  setLongtermMondayTime,
  longtermFridayDow,
  setLongtermFridayDow,
  longtermFridayTime,
  setLongtermFridayTime,
  limitGuard,
  setLimitGuard,
  adxFilter,
  setAdxFilter,
  killSwitch,
  llmUsage,
  saving,
  onSaveRuntime,
}) {
  const [sectionEyebrow, sectionTitle, sectionDescription] = SECTION_COPY[active] || SECTION_COPY.decision

  return (
    <>
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
          {active === 'decision' && (
            <>
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
                <div className="space-y-3">
                  <Weights weights={draftWeights} />
                  <div className="grid gap-2 sm:grid-cols-3">
                    <NumberInput value={weightQuant} min={0} max={100} onChange={setWeightQuant} suffix="量化%" />
                    <NumberInput value={weightTechnical} min={0} max={100} onChange={setWeightTechnical} suffix="技术%" />
                    <NumberInput value={weightSentiment} min={0} max={100} onChange={setWeightSentiment} suffix="情感%" />
                  </div>
                  <div className={`text-xs ${weightTotal === 100 ? 'text-stone-500 dark:text-slate-400' : 'text-red-600 dark:text-red-300'}`}>
                    权重合计 {weightTotal}%，建议保持 100%。
                  </div>
                </div>
              </SettingRow>
            </>
          )}
          {active === 'portfolio' && (
            <>
              <SettingRow label="风险经理" hint="启用后，RiskManager 可根据大盘、涨跌停、长期标签否决或降级信号。">
                <Toggle value={riskManager} onChange={setRiskManager} danger />
              </SettingRow>
              <SettingRow label="移动止损" hint="启用后，持仓跟踪模块可按 ATR trailing stop 更新动态止损。">
                <Toggle value={trailingStop} onChange={setTrailingStop} />
              </SettingRow>
              <SettingRow label="单股仓位上限" hint="当前运行时配置，只在后端白名单中展示。">
                <NumberInput value={maxStockPct} min={0} max={100} onChange={setMaxStockPct} suffix="%" />
              </SettingRow>
              <SettingRow label="板块仓位上限" hint="同一行业或板块的最大总暴露。">
                <NumberInput value={maxSectorPct} min={0} max={100} onChange={setMaxSectorPct} suffix="%" />
              </SettingRow>
              <SettingRow label="总仓位上限" hint="Portfolio Manager 约束使用。">
                <NumberInput value={maxTotalPct} min={0} max={100} onChange={setMaxTotalPct} suffix="%" />
              </SettingRow>
            </>
          )}
          {active === 'agents' && (
            <>
              <SettingRow label="多 Agent 决策" hint="控制盘后是否走 Analyst → Director → Researcher → Trader → RiskManager。">
                <Toggle value={multiAgent} onChange={setMultiAgent} />
              </SettingRow>
              <SettingRow label="长期分析师团" hint="控制周频长期标签生成和展示，不单独改变官方动作。">
                <Toggle value={longTermTeam} onChange={setLongTermTeam} />
              </SettingRow>
              <SettingRow label="长期约束官方动作" hint="关闭时长期标签只展示和留痕，不改推荐、分数或仓位；验证通过后再开启。">
                <Toggle value={longTermConstraints} onChange={setLongTermConstraints} danger />
              </SettingRow>
              <SettingRow label="手动长期团" hint="立即提交长期研究团队后台任务。">
                <ActionButton disabled={actionBusy === 'longterm'} onClick={onRunLongTermTeam}>
                  跑长期团
                </ActionButton>
              </SettingRow>
            </>
          )}
          {active === 'data' && (
            <>
              <SettingRow label="活跃标的" hint="当前 watchlist active=true 的股票数量。">
                <MiniStat label="stocks" value={cov.active_stocks ?? '-'} />
              </SettingRow>
              <SettingRow label="财报回填年限" hint="长期研究团队同步财务数据时回看的年份数量。">
                <NumberInput value={financialYears} min={1} max={10} onChange={setFinancialYears} suffix="年" />
              </SettingRow>
              <SettingRow label="新闻补缺阈值" hint="DB 内新闻数量低于该值时，先用 iFinD MCP 资讯/公告补充；仍不足再走 Tavily。">
                <NumberInput value={tavilyThreshold} min={0} max={10} onChange={setTavilyThreshold} />
              </SettingRow>
              <SettingRow label="Anspire 新闻窗口" hint="显式 deep research / 手动严格新闻抓取的回看天数。">
                <NumberInput value={anspireDays} min={1} max={7} onChange={setAnspireDays} suffix="天" />
              </SettingRow>
              <SettingRow label="Anspire 结果上限" hint="显式 Anspire 抓取时每股最多读取的搜索结果。">
                <NumberInput value={anspireMaxResults} min={1} max={20} onChange={setAnspireMaxResults} />
              </SettingRow>
              <SettingRow label="Anspire 补入标题" hint="显式 Anspire 抓取时每股最多补入情感分析链路的标题数。">
                <NumberInput value={anspireMaxAdd} min={0} max={10} onChange={setAnspireMaxAdd} />
              </SettingRow>
              <SettingRow label="Anspire 最低审计分" hint="显式 Anspire 抓取时低于该分数的新闻不会进入情感分析链路。">
                <NumberInput value={anspireMinScore} min={0} max={100} onChange={setAnspireMinScore} />
              </SettingRow>
              <SettingRow label="价格覆盖" hint="已有价格数据的标的数量。">
                <MiniStat label="prices" value={cov.price_covered ?? '-'} />
              </SettingRow>
              <SettingRow label="24h 新闻" hint="最近 24 小时有新闻覆盖的标的数量。">
                <MiniStat label="news" value={cov.news_24h_covered ?? '-'} />
              </SettingRow>
              <SettingRow label="三市场数据层" hint="A/HK/US 七层数据能力，只读展示，不代表港美已进入正式信号。">
                <MarketCapabilityMatrix catalog={cov.market_capability_catalog} coverage={cov.market_coverage} />
              </SettingRow>
            </>
          )}
          {active === 'schedule' && (
            <>
              <SettingRow label="调度运行状态" hint="展示最近一次任务状态、错误和完成时间。">
                <SchedulerState state={health?.scheduler || systemStatus?.scheduler} />
              </SettingRow>
              <SettingRow label="冷启动初始化" hint="回填价格历史、同步财报、披露日并生成首批信号。">
                <ActionButton disabled={initStatus?.running} onClick={onInitialize}>
                  {initStatus?.running ? '初始化中…' : '立即初始化'}
                </ActionButton>
              </SettingRow>
              <SettingRow label="每日复盘" hint="复盘页会在每天 15:00 后自动 ensure。">
                <TimeInput value={dailyReviewTime} onChange={setDailyReviewTime} />
              </SettingRow>
              <SettingRow label="长期复盘" hint="复盘页和调度按两组周内日期与时间触发。">
                <div className="flex flex-wrap items-center gap-2">
                  <DayInput value={longtermMondayDow} onChange={setLongtermMondayDow} />
                  <TimeInput value={longtermMondayTime} onChange={setLongtermMondayTime} />
                  <DayInput value={longtermFridayDow} onChange={setLongtermFridayDow} />
                  <TimeInput value={longtermFridayTime} onChange={setLongtermFridayTime} />
                </div>
              </SettingRow>
            </>
          )}
          {active === 'risk' && (
            <>
              <SettingRow label="大盘择时过滤" hint="启用后，盘后信号会用 RSRS 与板块扩散对强信号做衰减。">
                <Toggle value={limitGuard} onChange={setLimitGuard} />
              </SettingRow>
              <SettingRow label="ADX 震荡过滤" hint="启用后，技术分在震荡市按 ADX 系数衰减。">
                <Toggle value={adxFilter} onChange={setAdxFilter} />
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
            </>
          )}
          {active === 'memory' && (
            <div className="py-2">
              <MemorySection />
            </div>
          )}
          {active === 'llmcost' && <LlmCostPanel llmUsage={llmUsage} />}
          {active !== 'memory' && active !== 'llmcost' && (
            <SettingRow label="保存运行时配置" hint="只影响当前后端进程；重启后仍以 .env 为准。">
              <ActionButton onClick={onSaveRuntime} disabled={saving}>
                {saving ? '保存中' : '应用'}
              </ActionButton>
            </SettingRow>
          )}
        </div>
      </section>
    </>
  )
}

function LlmCostPanel({ llmUsage }) {
  return (
    <div className="space-y-4 py-2">
      {!llmUsage ? (
        <p className="text-xs text-stone-500 dark:text-slate-400">加载中…</p>
      ) : (
        <>
          <div>
            <div className={`${LABEL} mb-2`}>7 天总计</div>
            <div className="flex flex-wrap gap-3 text-xs">
              <span className="rounded border border-stone-300 px-2 py-1 dark:border-slate-600">
                调用 <strong>{llmUsage.total?.calls ?? 0}</strong> 次
              </span>
              <span className="rounded border border-stone-300 px-2 py-1 dark:border-slate-600">
                tokens_in <strong>{(llmUsage.total?.tokens_in ?? 0).toLocaleString()}</strong>
              </span>
              <span className="rounded border border-stone-300 px-2 py-1 dark:border-slate-600">
                tokens_out <strong>{(llmUsage.total?.tokens_out ?? 0).toLocaleString()}</strong>
              </span>
              <span className="rounded border border-stone-300 px-2 py-1 dark:border-slate-600">
                估算成本 <strong>¥{(llmUsage.total?.cost_estimate_cny ?? 0).toFixed(4)}</strong>
              </span>
            </div>
          </div>
          {llmUsage.buckets && Object.keys(llmUsage.buckets).length > 0 && (
            <div>
              <div className={`${LABEL} mb-2`}>按 Bucket 分桶</div>
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr className="text-stone-500 dark:text-slate-400">
                    <th className="pb-1 pr-4 text-left font-medium">bucket</th>
                    <th className="pb-1 pr-4 text-right font-medium">调用</th>
                    <th className="pb-1 pr-4 text-right font-medium">tokens_in</th>
                    <th className="pb-1 pr-4 text-right font-medium">tokens_out</th>
                    <th className="pb-1 text-right font-medium">¥ 估算</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(llmUsage.buckets).map(([bk, v]) => (
                    <tr key={bk} className="border-t border-stone-200 dark:border-slate-700">
                      <td className="py-1 pr-4 font-mono">{bk}</td>
                      <td className="py-1 pr-4 text-right">{v.calls}</td>
                      <td className="py-1 pr-4 text-right">{v.tokens_in.toLocaleString()}</td>
                      <td className="py-1 pr-4 text-right">{v.tokens_out.toLocaleString()}</td>
                      <td className="py-1 text-right">¥{v.cost_estimate_cny.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {llmUsage.daily && llmUsage.daily.length > 0 && (
            <div>
              <div className={`${LABEL} mb-2`}>每日明细（最近 7 天）</div>
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr className="text-stone-500 dark:text-slate-400">
                    <th className="pb-1 pr-4 text-left font-medium">日期</th>
                    <th className="pb-1 pr-4 text-right font-medium">调用</th>
                    <th className="pb-1 pr-4 text-right font-medium">tokens_in</th>
                    <th className="pb-1 pr-4 text-right font-medium">tokens_out</th>
                    <th className="pb-1 text-right font-medium">¥ 估算</th>
                  </tr>
                </thead>
                <tbody>
                  {llmUsage.daily.map((d) => (
                    <tr key={d.date} className="border-t border-stone-200 dark:border-slate-700">
                      <td className="py-1 pr-4 font-mono">{d.date}</td>
                      <td className="py-1 pr-4 text-right">{d.calls}</td>
                      <td className="py-1 pr-4 text-right">{d.tokens_in.toLocaleString()}</td>
                      <td className="py-1 pr-4 text-right">{d.tokens_out.toLocaleString()}</td>
                      <td className="py-1 text-right">¥{d.cost_estimate_cny.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!llmUsage.total?.calls && (
            <p className="text-xs text-stone-500 dark:text-slate-400">暂无记录（数据将在下次 LLM 调用后开始累积）</p>
          )}
        </>
      )}
    </div>
  )
}

function MarketCapabilityMatrix({ catalog, coverage = {} }) {
  const markets = catalog?.markets || []
  const detail = catalog?.markets_detail || {}
  if (!markets.length) {
    return <span className="text-xs text-stone-500 dark:text-slate-400">暂无能力目录</span>
  }
  const statusClass = {
    production: 'border-emerald-600/30 bg-emerald-600/10 text-emerald-700 dark:text-emerald-200',
    seeded: 'border-cyan-700/30 bg-cyan-700/10 text-cyan-800 dark:text-cyan-200',
    partial: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-200',
    observe_only: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-200',
    planned: 'border-stone-300 bg-[#f3eddc] text-stone-600 dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-300',
  }
  return (
    <div className="space-y-2">
      {markets.map((market) => {
        const info = detail[market] || {}
        const stats = coverage?.[market] || {}
        return (
          <div key={market} className="rounded-sm border border-stone-300 bg-[#f3eddc] p-2 dark:border-slate-700 dark:bg-[#161b25]">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-mono text-xs font-semibold text-stone-950 dark:text-slate-100">{market}</span>
              <span className={`rounded-sm border px-1.5 py-0.5 text-[10px] font-semibold ${statusClass[info.status] || statusClass.planned}`}>
                {info.status || 'unknown'}
              </span>
            </div>
            <div className="mt-1 font-mono text-[10px] text-stone-500 dark:text-slate-400">
              active {stats.active_stocks ?? 0} · price {stats.price_covered ?? 0} · financial {stats.financial_covered ?? 0}
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {(info.layers || []).map((layer) => (
                <span key={layer.id} className={`rounded-sm border px-1.5 py-0.5 text-[10px] ${statusClass[layer.status] || statusClass.planned}`}>
                  {layer.label}
                </span>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function AdminSidebarCards({
  initStatus,
  onInitialize,
  summary,
  runtime,
  weights,
  threshold,
  profile,
  weightQuant,
  weightTechnical,
  weightSentiment,
  maxTotalPct,
  riskManager,
  message,
  cov,
  systemStatus,
  health,
  modelStatus,
  actionBusy,
  onTrainModel,
  onRunLongTermTeam,
  killSwitch,
  onResetKillSwitch,
  onTriggerKillSwitch,
  deepTopic,
  setDeepTopic,
  deepSymbols,
  setDeepSymbols,
  deepResult,
  onDeepResearch,
}) {
  return (
    <aside className="space-y-4">
      <section className={PANEL}>
        <div className="border-b border-stone-300 p-4 dark:border-slate-700">
          <div className={LABEL}>冷启动</div>
          <div className="mt-1 text-sm italic text-stone-950 dark:text-slate-100">一键初始化数据</div>
        </div>
        <div className="space-y-3 p-4">
          <p className="text-xs leading-relaxed text-stone-500 dark:text-slate-400">
            首次使用或新加股票后运行：回填价格历史 → 同步财报 → 披露日 → 生成第一批信号。
          </p>
          {initStatus && initStatus.step !== 'idle' && (
            <div>
              <InitStepBar step={initStatus.step} />
              {initStatus.log.length > 0 && (
                <div className="mt-2 max-h-36 overflow-y-auto rounded-sm border border-stone-300 bg-[#f3eddc] p-2 font-mono text-[10px] leading-relaxed text-stone-600 dark:border-slate-700 dark:bg-[#161b25] dark:text-slate-300">
                  {initStatus.log.slice(-12).map((line, i) => (
                    <div key={i}>{line}</div>
                  ))}
                </div>
              )}
              {initStatus.step === 'done' && initStatus.counts && (
                <div className="mt-2 grid grid-cols-3 gap-2">
                  <MiniStat label="价格条" value={initStatus.counts.price_rows ?? 0} />
                  <MiniStat label="财报条" value={initStatus.counts.financial_rows ?? 0} />
                  <MiniStat label="披露日" value={initStatus.counts.disclosure_rows ?? 0} />
                </div>
              )}
              {initStatus.step === 'error' && (
                <div className="mt-2 rounded-sm border border-red-400/40 bg-red-400/10 p-2 text-xs text-red-700 dark:text-red-300">
                  {initStatus.error}
                </div>
              )}
            </div>
          )}
          <ActionButton disabled={initStatus?.running} onClick={onInitialize}>
            {initStatus?.running ? '初始化中…' : '立即初始化'}
          </ActionButton>
        </div>
      </section>

      <section className={PANEL}>
        <div className="border-b border-stone-300 p-4 dark:border-slate-700">
          <div className={LABEL}>草稿差异</div>
          <div className="mt-1 text-sm italic text-stone-950 dark:text-slate-100">草稿 vs 当前运行</div>
        </div>
        <div className="space-y-3 p-4">
          <DiffRow path="decision.entry_threshold" before={summary?.system?.entry_threshold ?? '-'} after={threshold} />
          <DiffRow path="decision.profile" before={summary?.system?.profile ?? '-'} after={profile} />
          <DiffRow path="decision.weights" before={`${Math.round(weights.quant * 100)}/${Math.round(weights.technical * 100)}/${Math.round(weights.sentiment * 100)}`} after={`${weightQuant}/${weightTechnical}/${weightSentiment}`} />
          <DiffRow path="portfolio.max_total" before={`${Math.round((runtime?.max_total_equity_pct || 0) * 100)}%`} after={`${maxTotalPct}%`} />
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
            <ActionButton disabled={actionBusy === 'train'} onClick={onTrainModel}>
              训练模型
            </ActionButton>
            <ActionButton disabled={actionBusy === 'longterm'} onClick={onRunLongTermTeam}>
              跑长期团
            </ActionButton>
            {killSwitch ? (
              <ActionButton danger disabled={actionBusy === 'reset'} onClick={onResetKillSwitch}>
                重置熔断
              </ActionButton>
            ) : (
              <ActionButton danger disabled={actionBusy === 'trigger'} onClick={onTriggerKillSwitch}>
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
        <form onSubmit={onDeepResearch} className="space-y-3 p-4">
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
            ['05-15', '信号规则更新'],
          ].map(([time, text]) => (
            <div key={`${time}-${text}`} className="grid grid-cols-[52px_1fr] gap-3 border-b border-stone-300 pb-3 text-sm last:border-0 last:pb-0 dark:border-slate-700">
              <span className="font-mono text-xs text-stone-500 dark:text-slate-400">{time}</span>
              <span className="text-stone-950 dark:text-slate-100">{text}</span>
            </div>
          ))}
        </div>
      </section>
    </aside>
  )
}
