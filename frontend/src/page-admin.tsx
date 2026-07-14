// ============================================================
// 治理台 — 决策 / 仓位 / Agent / 数据 / 调度 / 熔断 / 记忆 / LLM 成本
// ============================================================
import React from 'react';
import {
  resetKillSwitch,
  runDeepResearch,
  trainModel,
  triggerKillSwitch,
  triggerLongTermTeam,
} from './services/api';
import { Badge, Card, McIcon, Metric, PageHead, Seg, Toggle, toast, useStore } from './shared';
const { useState: useAState, useEffect: useAEffect } = React;

const ADMIN_SECTIONS = [
  ['decision', '裁决规则', '阈值 / 权重', 'decision'],
  ['portfolio', '仓位纪律', '仓位 / 出场', 'portfolio'],
  ['agents', '研究团队', '辩论 / 动作', 'agents'],
  ['apikey', '本地凭证', '密钥 / 安全', 'apikey'],
  ['data', '来源与新鲜度', '价格 / 新闻', 'data'],
  ['schedule', '工作流节奏', 'A股日历', 'schedule'],
  ['risk', '熔断保护', '风控保护', 'risk'],
  ['memory', '记忆治理', '元数据 / 审计', 'memory'],
  ['llmcost', '研究成本账本', '7 天用量', 'llmcost'],
];

function SettingRow({ label, hint, children }: any) {
  return (
    <div className="spread" style={{ padding: '12px 0', borderBottom: '1px solid var(--hairline-soft)', gap: 16 }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13.5, fontWeight: 570 }}>{label}</div>
        {hint && <div className="t-faint" style={{ fontSize: 12, marginTop: 2, lineHeight: 1.5 }}>{hint}</div>}
      </div>
      <div className="row" style={{ flex: 'none', gap: 8 }}>{children}</div>
    </div>
  );
}

function NumSlider({ value, onChange, min, max, step = 1, unit = '' }: any) {
  return (
    <div className="row" style={{ gap: 10 }}>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))}
        style={{ width: 130, accentColor: 'var(--accent)' }} />
      <span className="t-num" style={{ fontSize: 13, fontWeight: 650, width: 52, textAlign: 'right' }}>{value}{unit}</span>
    </div>
  );
}

function DecisionSection({ cfg, set }: any) {
  const wsum = cfg.weights.quant + cfg.weights.technical + cfg.weights.sentiment;
  return (
    <div>
      <SettingRow label="规则档案 Profile" hint="new_framework 为当前默认决策框架">
        <Seg value={cfg.profile} options={[['new_framework', 'new_framework'], ['legacy', 'legacy']]} onChange={(v) => set({ profile: v })} />
      </SettingRow>
      <SettingRow label="入场阈值" hint="综合分超过该阈值才可进入「可小仓试错」">
        <NumSlider value={cfg.entry_threshold} onChange={(v) => set({ entry_threshold: v })} min={0} max={60} />
      </SettingRow>
      <SettingRow label="研究总监最低置信度" hint="低于该置信度的裁决只展示，不给动作建议">
        <NumSlider value={cfg.director_min_confidence} onChange={(v) => set({ director_min_confidence: v })} min={0} max={100} unit="%" />
      </SettingRow>
      <SettingRow label="信号权重" hint={`技术 ${cfg.weights.technical}% + 情感 ${cfg.weights.sentiment}% + 量化 ${cfg.weights.quant}%(量化休眠) · 合计 ${wsum}%`}>
        <div className="grid" style={{ gap: 6 }}>
          {[['technical', '技术'], ['sentiment', '情感'], ['quant', '量化']].map(([k, l]) => (
            <div key={k} className="row" style={{ gap: 8 }}>
              <span className="t-faint" style={{ fontSize: 11.5, width: 28 }}>{l}</span>
              <NumSlider value={cfg.weights[k]} onChange={(v) => set({ weights: { ...cfg.weights, [k]: v } })} min={0} max={100} unit="%" />
            </div>
          ))}
        </div>
      </SettingRow>
      <SettingRow label="Regime Filter" hint="根据大盘环境(RSRS / 扩散度)对信号做过滤或衰减">
        <Toggle on={cfg.regime_filter} onChange={(v) => set({ regime_filter: v })} label="Regime Filter" />
      </SettingRow>
      <SettingRow label="ADX 震荡市过滤" hint="默认关闭;开启后震荡市信号降级">
        <Toggle on={cfg.adx_filter} onChange={(v) => set({ adx_filter: v })} label="ADX Filter" />
      </SettingRow>
    </div>
  );
}

function PortfolioSection({ cfg, set }: any) {
  return (
    <div>
      <SettingRow label="单股仓位上限" hint="任何单一标的不超过总资产的该比例">
        <NumSlider value={cfg.max_stock_pct} onChange={(v) => set({ max_stock_pct: v })} min={1} max={50} unit="%" />
      </SettingRow>
      <SettingRow label="行业仓位上限" hint="同一行业集中度限制，同板块持仓合并计算">
        <NumSlider value={cfg.max_sector_pct} onChange={(v) => set({ max_sector_pct: v })} min={5} max={80} unit="%" />
      </SettingRow>
      <SettingRow label="总权益上限" hint="股票总仓位上限，余下保留现金">
        <NumSlider value={cfg.max_total_pct} onChange={(v) => set({ max_total_pct: v })} min={10} max={100} unit="%" />
      </SettingRow>
      <SettingRow label="新信号试错仓" hint="新信号默认映射的初始小仓位">
        <div className="row" style={{ gap: 7 }}><span className="t-num">{cfg.new_signal_trial_pct}%</span><Badge tone="badge-dim">需修改 .env 后重启</Badge></div>
      </SettingRow>
      <SettingRow label="ATR 移动止损" hint="用 trailing ATR 保护趋势浮盈;触发时提醒，不自动卖出">
        <Toggle on={cfg.trailing_stop} onChange={(v) => set({ trailing_stop: v })} label="移动止损" />
      </SettingRow>
    </div>
  );
}

function AgentsSection({ cfg, set }: any) {
  const [topic, setTopic] = useAState('');
  const [symbols, setSymbols] = useAState('');
  const [running, setRunning] = useAState('');
  const [confirming, setConfirming] = useAState('');
  async function run(kind, label) {
    setRunning(kind);
    setConfirming('');
    try {
      if (kind === 'deep') {
        const parsedSymbols = symbols.split(/[,，\s]+/).map((value) => value.trim()).filter(Boolean);
        await runDeepResearch({ topic: topic.trim(), symbols: parsedSymbols, as_of: null });
      } else {
        await triggerLongTermTeam();
      }
      toast(`${label}已提交到后端，结果不会覆盖官方信号`);
    } catch (error: any) {
      toast(`${label}失败:${error?.message || '后端错误'}`);
    } finally {
      setRunning('');
    }
  }
  return (
    <div>
      <SettingRow label="多空辩论(Multi-Agent)" hint="bull/bear 多轮观点与裁定，LLM 成本计入预算">
        <Toggle on={cfg.multi_agent} onChange={(v) => set({ multi_agent: v })} label="多空辩论" />
      </SettingRow>
      <SettingRow label="风险经理" hint="从风险角度二次拦截信号;只能做减法，不能制造 alpha">
        <Toggle on={cfg.risk_manager} onChange={(v) => set({ risk_manager: v })} label="风险经理" />
      </SettingRow>
      <SettingRow label="长期研究团队" hint="质量 / 景气 / 资金流分析师聚合慢变量标签">
        <Toggle on={cfg.long_term_team} onChange={(v) => set({ long_term_team: v })} label="长期研究团队" />
      </SettingRow>
      <SettingRow label="长期标签约束官方动作" hint="通过质量门的长期标签可压缩短线仓位上限">
        <Toggle on={cfg.long_term_constraints} onChange={(v) => set({ long_term_constraints: v })} label="长期约束" />
      </SettingRow>
      <SettingRow label="LLM Provider" hint="local_cli 模式无需 API Key，使用本地 agent">
        <div className="row" style={{ gap: 7 }}><Badge tone="badge-accent">{cfg.llm_provider}</Badge><span className="t-faint" style={{ fontSize: 11.5 }}>需修改 .env 后重启</span></div>
      </SettingRow>
      <div className="glass-inset" style={{ padding: 14, marginTop: 14 }}>
        <div className="t-eyebrow">手动触发(需确认 · 会调用 LLM / 搜索)</div>
        <div className="row" style={{ marginTop: 10, gap: 8, flexWrap: 'wrap' }}>
          <input className="field" style={{ flex: 1, minWidth: 170 }} value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="深度研究主题，如:AI 光模块供需" />
          <input className="field" style={{ width: 150 }} value={symbols} onChange={(e) => setSymbols(e.target.value)} placeholder="标的，逗号分隔" />
          <button className="btn btn-sm" disabled={!topic || !!running} onClick={() => confirming === 'deep' ? run('deep', '深度研究') : setConfirming('deep')}>{running === 'deep' ? '研究中…' : confirming === 'deep' ? '确认运行深度研究' : '运行深度研究'}</button>
          <button className="btn btn-sm" disabled={!!running} onClick={() => confirming === 'lt' ? run('lt', '长期研究团队') : setConfirming('lt')}>{running === 'lt' ? '运行中…' : confirming === 'lt' ? '确认运行长期团队' : '运行长期团队'}</button>
          {confirming && <button className="btn btn-sm btn-quiet" onClick={() => setConfirming('')}>取消</button>}
        </div>
      </div>
      <ActionRegistryPanel />
    </div>
  );
}

function ActionRegistryPanel() {
  const actions = [
    ['watchlist.add', 'medium', 'confirm', '研究池', '新增观察标的，不会生成买入信号'],
    ['position.add', 'high', 'confirm', '持仓账本', '只记录持仓，不接券商、不下单'],
    ['research.deep.run', 'medium', 'confirm', '研究状态', '输出 observe-only 深研案卷'],
    ['memory.candidate.write', 'medium', 'gate', '记忆候选', '需要来源门控和人工确认'],
    ['config.update', 'high', 'confirm', '运行时配置', '仅保存草稿，下次裁决生效'],
  ];
  const T = window.MC_DATA.TOOLS_REGISTRY;
  return (
    <div className="glass-inset" style={{ padding: 14, marginTop: 14 }}>
      <div className="spread" style={{ flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div className="t-eyebrow">Action Registry · 待确认动作</div>
          <div className="t-faint" style={{ fontSize: 12, marginTop: 3 }}>所有写入型动作先形成 pending action，确认前不写数据库。</div>
        </div>
        <Badge tone="badge-dim">{T.counts.stable + T.counts.maintenance + T.counts.evidence + T.counts.attic} tools indexed</Badge>
      </div>
      <div className="grid" style={{ gap: 7, marginTop: 12 }}>
        {actions.map(([name, risk, guard, target, note]) => (
          <div key={name} className="spread" style={{ gap: 10 }}>
            <div style={{ minWidth: 0 }}>
              <div className="t-num" style={{ fontSize: 12.5, fontWeight: 650 }}>{name}</div>
              <div className="t-faint" style={{ fontSize: 11.5, marginTop: 2, lineHeight: 1.45 }}>{target} · {note}</div>
            </div>
            <div className="row" style={{ gap: 5, flex: 'none' }}>
              <Badge tone={risk === 'high' ? 'badge-up' : 'badge-warn'}>{risk}</Badge>
              <Badge tone="badge-dim">{guard}</Badge>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function DataSection({ cfg, set }: any) {
  return (
    <div>
      <SettingRow label="财务回填年数" hint="长期研究与 Piotroski 评分所需的财务数据深度">
        <NumSlider value={cfg.financial_years} onChange={(v) => set({ financial_years: v })} min={1} max={10} unit="年" />
      </SettingRow>
      <SettingRow label="Tavily 补充阈值" hint="DB 新闻少于该数量时触发实时搜索补充(需 TAVILY_API_KEY)">
        <NumSlider value={cfg.tavily_threshold} onChange={(v) => set({ tavily_threshold: v })} min={0} max={10} unit="条" />
      </SettingRow>
      <SettingRow label="Anspire 新闻窗口" hint="严格新闻抓取的回看天数(需 ANSPIRE_API_KEY)">
        <NumSlider value={cfg.anspire_days} onChange={(v) => set({ anspire_days: v })} min={1} max={7} unit="天" />
      </SettingRow>
      <SettingRow label="Anspire 单次最多入库" hint={`最多返回 ${cfg.anspire_max_results} 条，质量分 ≥ ${cfg.anspire_min_score} 的最多入库 ${cfg.anspire_max_add} 条`}>
        <NumSlider value={cfg.anspire_max_add} onChange={(v) => set({ anspire_max_add: v })} min={0} max={5} unit="条" />
      </SettingRow>
      <SettingRow label="Anspire 最低质量分" hint="低于该分数的新闻不入库，只留审计痕迹">
        <NumSlider value={cfg.anspire_min_score} onChange={(v) => set({ anspire_min_score: v })} min={50} max={100} />
      </SettingRow>
    </div>
  );
}

function ScheduleSection({ cfg, set }: any) {
  const W = window.MC_DATA.WORKFLOWS;
  return (
    <div>
      <SettingRow label="调度器" hint="默认关闭(手动模式);开启后按 A股交易日历自动运行盘前 / 盘后任务">
        <div className="row" style={{ gap: 7 }}><Badge tone={cfg.scheduler_enabled ? 'badge-up' : 'badge-dim'}>{cfg.scheduler_enabled ? '已启用' : '未启用'}</Badge><span className="t-faint" style={{ fontSize: 11.5 }}>需修改 .env 后重启</span></div>
      </SettingRow>
      <SettingRow label="每日复盘时间" hint="收盘后生成当日信号与复盘">
        <input className="field" type="time" style={{ width: 110 }} value={cfg.daily_review_time} onChange={(e) => set({ daily_review_time: e.target.value })} />
      </SettingRow>
      <SettingRow label="长期复盘 · 周一" hint="周初慢变量检查">
        <input className="field" type="time" style={{ width: 110 }} value={cfg.longterm_monday_time} onChange={(e) => set({ longterm_monday_time: e.target.value })} />
      </SettingRow>
      <SettingRow label="长期复盘 · 周五" hint="周末长期标签与周度反思">
        <input className="field" type="time" style={{ width: 110 }} value={cfg.longterm_friday_time} onChange={(e) => set({ longterm_friday_time: e.target.value })} />
      </SettingRow>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8, marginTop: 14 }}>
        {W.map((w) => (
          <div key={w.id} className="glass-inset" style={{ padding: 13 }}>
            <div className="spread" style={{ gap: 8 }}>
              <span style={{ fontSize: 13.5, fontWeight: 650 }}>{w.label}</span>
              <Badge tone={w.tone}>{w.status}</Badge>
            </div>
            <div className="t-dim" style={{ fontSize: 12.2, lineHeight: 1.5, marginTop: 7 }}>{w.summary}</div>
            <div className="t-num t-faint" style={{ fontSize: 11, marginTop: 7 }}>{w.side_effect}</div>
          </div>
        ))}
      </div>
      <div className="glass-inset" style={{ padding: 13, marginTop: 10, fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
        工作流契约:盘前同步数据 / 检查覆盖，盘中只读缓存 / 止损观察，盘后全市场信号 / 复盘 / 导出 / 记忆候选，周末长期标签 / 周度反思。所有写入型 job 默认 dry-run 或 pending confirmation。
      </div>
    </div>
  );
}

function RiskSection({ cfg, set }: any) {
  const [confirming, setConfirming] = useAState(false);
  const [busy, setBusy] = useAState(false);
  async function trigger() {
    setBusy(true);
    try {
      await triggerKillSwitch('web_governance');
      set({ kill_switch: true });
      setConfirming(false);
      toast('熔断已由后端触发:调度与写入已阻断', 'warn');
    } catch (error: any) {
      toast(`触发熔断失败:${error?.message || '后端错误'}`);
    } finally {
      setBusy(false);
    }
  }
  async function reset() {
    setBusy(true);
    try {
      await resetKillSwitch();
      set({ kill_switch: false });
      toast('后端熔断已复位，系统恢复正常');
    } catch (error: any) {
      toast(`复位熔断失败:${error?.message || '后端错误'}`);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div>
      <div className="glass-inset" style={{ padding: 16, borderColor: cfg.kill_switch ? 'var(--up)' : undefined }}>
        <div className="spread" style={{ flexWrap: 'wrap', gap: 10 }}>
          <div>
            <div className="row" style={{ gap: 8 }}>
              <span style={{ fontSize: 15, fontWeight: 650 }}>Kill Switch 熔断</span>
              <Badge tone={cfg.kill_switch ? 'badge-up' : 'badge-down'}>{cfg.kill_switch ? '已触发' : '未触发'}</Badge>
            </div>
            <div className="t-dim" style={{ fontSize: 12.5, marginTop: 4, maxWidth: 460, lineHeight: 1.55 }}>
              触发后阻断所有调度任务与风险动作(信号生成、自动写入)，只保留只读查询。用于异常行情或数据污染时的紧急保护。
            </div>
          </div>
          {cfg.kill_switch ? (
            <button className="btn btn-primary" disabled={busy} onClick={reset}>{busy ? '处理中…' : '复位熔断'}</button>
          ) : confirming ? (
            <div className="row" style={{ gap: 6 }}>
              <button className="btn btn-danger" disabled={busy} style={{ borderColor: 'var(--up)', color: 'var(--up)' }} onClick={trigger}>{busy ? '处理中…' : '确认触发'}</button>
              <button className="btn btn-quiet" onClick={() => setConfirming(false)}>取消</button>
            </div>
          ) : (
            <button className="btn btn-danger" onClick={() => setConfirming(true)}>触发熔断</button>
          )}
        </div>
      </div>
      <SettingRow label="Bark iOS 推送" hint="止损触发、熔断、复盘完成时推送提醒(需 BARK_KEY)">
        <Badge tone="badge-dim">未配置 Key</Badge>
      </SettingRow>
      <SettingRow label="LLM 预算报警" hint="7 天 LLM 成本超过 ¥10 时提醒;当前 ¥3.42">
        <div className="row" style={{ gap: 7 }}><Badge tone="badge-up">当前开启</Badge><span className="t-faint" style={{ fontSize: 11.5 }}>暂无网页配置接口</span></div>
      </SettingRow>
    </div>
  );
}

function MemorySectionPanel() {
  const [state] = useStore();
  const [tab, setTab] = useAState('items');
  const [confirmDel, setConfirmDel] = useAState<any>(null);
  const M = window.MC_DATA.MEMORY;
  const items = state.memoryItems;
  return (
    <div>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
        <Metric label="记忆总数" value={M.overview.total} />
        <Metric label="Trusted" value={M.overview.trusted} tone="up" />
        <Metric label="待确认候选" value={M.overview.candidate} tone="" />
        <Metric label="审计事件" value={M.overview.audit_events} />
      </div>
      <div style={{ marginTop: 14 }}>
        <Seg value={tab} options={[['items', '活跃记忆'], ['audit', '召回审计日志']]} onChange={setTab} />
      </div>
      {tab === 'items' ? (
        <div className="grid" style={{ gap: 8, marginTop: 12 }}>
          {items.map((m) => (
            <div key={m.id} className="glass-inset" style={{ padding: '11px 14px' }}>
              <div className="spread" style={{ flexWrap: 'wrap', gap: 6 }}>
                <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
                  <Badge tone={m.trust === 'trusted' ? 'badge-down' : 'badge-warn'}>{m.trust === 'trusted' ? 'trusted' : '候选'}</Badge>
                  <Badge tone="badge-dim">{m.category}</Badge>
                  <span className="t-num t-faint" style={{ fontSize: 11.5 }}>{m.scope}</span>
                </div>
                <div className="row" style={{ gap: 5 }}>
                  {m.trust !== 'trusted' && (
                    <button className="btn btn-sm" onClick={() => {
                      window.MC_LIVE.memoryConfirm(m.id)
                        .then(() => toast('记忆候选已确认升级为 trusted'))
                        .catch((e) => {
                          if (!e || !e.demo) { toast(`升级失败:${e?.message || '后端错误'}`); return; }
                          toast('示例模式不会升级记忆；连接本地后端后再试');
                        });
                    }}>确认升级</button>
                  )}
                  {confirmDel === m.id ? (
                    <React.Fragment>
                      <button className="btn btn-sm btn-danger" onClick={() => {
                        window.MC_LIVE.memoryDelete(m.id)
                          .then(() => toast('记忆已删除，审计日志保留'))
                          .catch((e) => {
                            if (!e || !e.demo) { toast(`删除失败:${e?.message || '后端错误'}`); return; }
                            toast('示例模式不会删除记忆；连接本地后端后再试');
                          });
                      }}>确认</button>
                      <button className="btn btn-sm btn-quiet" onClick={() => setConfirmDel(null)}>取消</button>
                    </React.Fragment>
                  ) : (
                    <button className="btn btn-sm btn-quiet btn-danger" onClick={() => setConfirmDel(m.id)}>删除</button>
                  )}
                </div>
              </div>
              <div style={{ fontSize: 13, marginTop: 7, lineHeight: 1.55 }}>{m.text}</div>
              <div className="t-num t-faint" style={{ fontSize: 11, marginTop: 4 }}>{m.date}</div>
            </div>
          ))}
        </div>
      ) : (
        <div className="grid" style={{ gap: 0, marginTop: 12 }}>
          {M.audit.map((a, i) => (
            <div key={i} className="row" style={{ gap: 12, padding: '10px 2px', borderBottom: i < M.audit.length - 1 ? '1px solid var(--hairline-soft)' : 'none', fontSize: 12.5 }}>
              <span className="t-num t-faint" style={{ width: 118, flex: 'none' }}>{a.time}</span>
              <Badge tone={a.action.includes('写入') ? 'badge-warn' : a.action.includes('升级') ? 'badge-up' : 'badge-accent'}>{a.action}</Badge>
              <span className="t-num t-faint">{a.target}</span>
              <span className="t-dim" style={{ minWidth: 0 }}>{a.context}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function LLMCostSection() {
  const U = window.MC_DATA.LLM_USAGE;
  const max = Math.max(...U.daily);
  const maxBucket = Math.max(...U.buckets.map((b) => b.cny));
  return (
    <div>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
        <Metric label="7 天成本" value={`¥${U.total_cny.toFixed(2)}`} />
        <Metric label="调用次数" value={U.total_calls} />
        <Metric label="预算上限" value="¥10.00" sub="超出时报警" />
      </div>
      <div className="t-eyebrow" style={{ marginTop: 16 }}>近 7 日每日成本(CNY)</div>
      <div className="row" style={{ alignItems: 'flex-end', gap: 8, height: 90, marginTop: 10 }}>
        {U.daily.map((v, i) => (
          <div key={i} style={{ flex: 1, textAlign: 'center' }}>
            <div style={{ height: `${(v / max) * 64}px`, borderRadius: 6, background: 'var(--accent)', opacity: 0.55 + (v / max) * 0.45, transition: 'height 0.4s' }}></div>
            <div className="t-num t-faint" style={{ fontSize: 10.5, marginTop: 4 }}>{v.toFixed(2)}</div>
          </div>
        ))}
      </div>
      <div className="t-eyebrow" style={{ marginTop: 16 }}>按 Bucket 分桶</div>
      <div className="grid" style={{ gap: 7, marginTop: 9 }}>
        {U.buckets.map((b) => (
          <div key={b.name} className="row" style={{ gap: 10 }}>
            <span style={{ fontSize: 12.5, width: 76, flex: 'none' }}>{b.name}</span>
            <div style={{ flex: 1, height: 7, borderRadius: 999, background: 'var(--chip-bg)' }}>
              <div style={{ width: `${(b.cny / maxBucket) * 100}%`, height: '100%', borderRadius: 999, background: 'var(--accent)' }}></div>
            </div>
            <span className="t-num t-faint" style={{ fontSize: 11.5, width: 96, textAlign: 'right' }}>{b.calls} 次 · ¥{b.cny.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function AdminSidebar() {
  const S = window.MC_DATA.SYSTEM;
  const [trainConfirm, setTrainConfirm] = useAState(false);
  const [training, setTraining] = useAState(false);
  async function startTraining() {
    setTraining(true);
    try {
      await trainModel();
      toast('模型训练任务已提交到后端');
      setTrainConfirm(false);
    } catch (error: any) {
      toast(`模型训练启动失败:${error?.message || '后端错误'}`);
    } finally {
      setTraining(false);
    }
  }
  return (
    <div className="grid" style={{ gap: 10, alignContent: 'start' }}>
      <div className="glass" style={{ padding: '14px 16px' }}>
        <div className="t-eyebrow">系统状态</div>
        <div className="grid" style={{ gap: 7, marginTop: 9, fontSize: 12.5 }}>
          {[['版本', `v${S.version}`], ['Agent 模式', S.health.agent_mode], ['自选标的', `${S.health.watchlist} 只`], ['持仓', `${S.health.positions} 笔`], ['记忆', `${S.health.memory} 条`], ['调度器', S.health.scheduler]].map(([k, v]) => (
            <div key={k} className="spread"><span className="t-faint">{k}</span><span className="t-num" style={{ fontWeight: 600 }}>{v}</span></div>
          ))}
        </div>
      </div>
      <div className="glass" style={{ padding: '14px 16px' }}>
        <div className="t-eyebrow">模型状态</div>
        <div className="grid" style={{ gap: 7, marginTop: 9, fontSize: 12.5 }}>
          {[['Qlib', S.model.qlib], ['Kronos', S.model.kronos], ['上次训练', S.model.last_train]].map(([k, v]) => (
            <div key={k} className="spread"><span className="t-faint">{k}</span><span style={{ fontWeight: 570 }}>{v}</span></div>
          ))}
        </div>
        <button className="btn btn-sm" disabled={training} style={{ marginTop: 12, width: '100%' }} onClick={() => trainConfirm ? startTraining() : setTrainConfirm(true)}>{training ? '提交中…' : trainConfirm ? '确认触发模型训练' : '触发模型训练'}</button>
      </div>
      <div className="glass" style={{ padding: '14px 16px' }}>
        <div className="t-eyebrow">导出</div>
        <div className="grid" style={{ gap: 6, marginTop: 10 }}>
          {[
            ['信号 CSV', '/api/export/signals.csv'],
            ['持仓 CSV', '/api/export/positions.csv'],
            ['复盘 CSV', '/api/export/reviews.csv'],
            ['盘后 HTML 报告', '/api/export/postmarket-review.html'],
          ].map(([label, path]) => (
            <button key={label} className="btn btn-sm" onClick={() => window.open(path, '_blank')}>{label}</button>
          ))}
        </div>
      </div>
    </div>
  );
}

function CredRow({ item }: any) {
  return (
    <div className="cred-row">
      <div style={{ minWidth: 0 }}>
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13.5, fontWeight: 600 }}>{item.name}</span>
          <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-3)', background: 'var(--chip-bg)', padding: '1px 6px', borderRadius: 5 }}>{item.env}</code>
        </div>
        <div className="t-faint" style={{ fontSize: 12, marginTop: 3, lineHeight: 1.5 }}>{item.hint}</div>
      </div>
      <div className="cred-action"><Badge tone="badge-dim">仅支持手动配置</Badge></div>
    </div>
  );
}

function ApiKeySection({ cfg }: any) {
  const llmLocal = cfg.llm_provider === 'local_cli';
  const llmEnv = cfg.llm_provider === 'anthropic' ? 'ANTHROPIC_API_KEY' : cfg.llm_provider === 'openai' ? 'OPENAI_API_KEY' : 'AI_PROVIDER=local_cli';
  const groups = [
    { label: '模型 LLM', keys: [
      { id: 'llm', name: `LLM Provider · ${cfg.llm_provider}`, env: llmEnv, disabled: llmLocal, tail: '7a2c',
        hint: llmLocal ? '当前 local_cli，走本机已登录的本地 CLI，无需云端 Key。在「LLM 与 Agent」可切换 provider。'
          : (cfg.llm_provider === 'openai' ? 'OpenAI 兼容(DeepSeek / Moonshot / 通义 / Azure);可另配 OPENAI_BASE_URL。' : '云端模型凭证，用于新闻情绪、多空辩论、研究副驾驶与 AI 对话。'),
        placeholder: '粘贴 API Key' },
    ] },
    { label: '行情数据源', keys: [
      { id: 'tushare', name: 'Tushare 前复权行情', env: 'TUSHARE_TOKEN', tail: 'c5e1',
        hint: '可选前复权日线 fallback，默认关闭(TUSHARE_QFQ_ENABLED);影响价格口径。', placeholder: 'token…' },
      { id: 'tickflow', name: 'TickFlow 行情', env: 'TICKFLOW_API_KEY', tail: '9e44',
        hint: '可选 CN 日线优先源(forward_additive 复权)，默认关闭;启用后作首选源。', placeholder: '粘贴 API Key' },
      { id: 'ifind', name: 'iFinD MCP · observe-only', env: 'IFIND_MCP_TOKEN', tail: '2b70',
        hint: '同花顺 iFinD MCP 探针，默认关闭，observe-only，不接入生产行情拉取。', placeholder: 'token…' },
    ] },
    { label: '新闻与搜索', keys: [
      { id: 'tavily', name: 'Tavily 实时搜索', env: 'TAVILY_API_KEY', tail: 'b91f',
        hint: 'DB 新闻不足阈值时补充实时搜索(可能触网和花费)。', placeholder: 'tvly-…' },
      { id: 'anspire', name: 'Anspire 严格新闻', env: 'ANSPIRE_API_KEY', tail: '4d80',
        hint: '深度研究与严格新闻抓取使用，带质量分门控入库。', placeholder: 'ans-…' },
    ] },
    { label: '推送与远程访问', keys: [
      { id: 'bark', name: 'Bark iOS 推送', env: 'BARK_KEY', tail: 'a7f3',
        hint: '止损触发、熔断、复盘完成时推送到 iPhone(可另配 BARK_SERVER)。', placeholder: 'bark key…' },
      { id: 'remote', name: '远程 Agent 访问', env: 'MINGCANG_AGENT_API_KEY', tail: '0b2d',
        hint: '远程暴露默认关闭且只读;开启远程写需显式 allowlist。本地优先建议留空。', placeholder: '自定义密钥…' },
    ] },
  ];
  return (
    <div>
      <div className="glass-inset" style={{ padding: '12px 15px', marginBottom: 4, fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
        <b style={{ color: 'var(--ink)' }}>本地优先</b> · 网页端不会写入 <code style={{ fontFamily: 'var(--font-mono)' }}>.env</code> 或接收明文密钥。请在本机配置后重启后端；密钥不进 Git、不上传浏览器存储。
      </div>
      {groups.map((g) => (
        <div key={g.label} style={{ marginTop: 16 }}>
          <div className="t-eyebrow" style={{ marginBottom: 2 }}>{g.label}</div>
          <div className="grid" style={{ gap: 0 }}>
            {g.keys.map((k) => (
              <CredRow key={k.id} item={k} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function AdminPage() {
  const [adState] = useStore();
  const [active, setActive] = useAState('decision');
  const [cfg, setCfg] = useAState({ ...window.MC_DATA.RUNTIME });
  const [saved, setSaved] = useAState(true);
  // live 配置晚于页面挂载到达时同步进表单;有未保存修改则不覆盖
  useAEffect(() => {
    if (saved) setCfg({ ...window.MC_DATA.RUNTIME });
  }, [adState.runtime]);
  function set(patch) { setCfg((c) => ({ ...c, ...patch })); setSaved(false); }
  function save() {
    window.MC_LIVE.saveRuntime(cfg)
      .then(() => { setSaved(true); toast('运行时配置已由后端应用 · 仅当前进程有效，重启后按 .env 恢复'); })
      .catch((e) => {
        if (!e || !e.demo) { toast(`保存失败:${e?.message || '后端错误'}`); return; }
        toast('示例模式不会保存配置；连接本地后端后再试');
      });
  }
  const idx = ADMIN_SECTIONS.findIndex(([id]) => id === active);
  const copy = {
    decision: '控制裁决分如何计算，以及哪些信号可以进入可小仓试错。',
    portfolio: '集中展示仓位、止损止盈和退出保护的纪律参数。',
    agents: '控制多空辩论、仲裁置信度、研究类 agent 和待确认动作注册。',
    apikey: '配置 LLM、新闻、数据与推送凭证。本地优先，只写本机 .env。',
    data: '检查价格、财报、新闻覆盖率，保留本地优先和来源门控策略。',
    schedule: '展示盘前、盘中、盘后、周末四段工作流和写入边界。',
    risk: '集中管理会阻断调度或跳过交易建议的保护性开关。',
    memory: '查看活跃记忆、确认候选升级、删除与召回审计日志。',
    llmcost: '每次 LLM 调用的 token 估算和 CNY 成本，按 bucket 分桶。',
  }[active];

  const body = {
    decision: <DecisionSection cfg={cfg} set={set} />,
    portfolio: <PortfolioSection cfg={cfg} set={set} />,
    agents: <AgentsSection cfg={cfg} set={set} />,
    apikey: <ApiKeySection cfg={cfg} />,
    data: <DataSection cfg={cfg} set={set} />,
    schedule: <ScheduleSection cfg={cfg} set={set} />,
    risk: <RiskSection cfg={cfg} set={(patch: any) => setCfg((current) => ({ ...current, ...patch }))} />,
    memory: <MemorySectionPanel />,
    llmcost: <LLMCostSection />,
  }[active];

  const needsSave = ['decision', 'portfolio', 'agents', 'data', 'schedule'].includes(active);

  return (
    <div className="grid" style={{ gap: 14 }}>
      <PageHead eyebrow="Governance" title="规则与信任治理台"
        desc="把裁决规则、仓位纪律、研究团队、来源新鲜度、调度节奏、熔断保护和记忆治理集中到一个可审计界面。标注「需确认」的操作可能影响正式信号。"
        right={cfg.kill_switch && <Badge tone="badge-up">⚠ 熔断已触发</Badge>} />
      <div className="grid" style={{ gridTemplateColumns: '200px minmax(0, 1fr) 248px', gap: 14, alignItems: 'start' }} data-grid="admin-cols">
        <nav className="glass pop admin-nav" style={{ padding: 7, position: 'sticky', top: 76 }} data-tour="admin-nav">
          {ADMIN_SECTIONS.map(([id, label, hint, icon]) => (
            <button key={id} type="button" className={`admin-navitem ${active === id ? 'on' : ''}`} onClick={() => setActive(id)}>
              <span className="admin-navitem-ic"><McIcon name={icon} size={17} /></span>
              <span style={{ minWidth: 0 }}>
                <span className="admin-navitem-label">{label}</span>
                <span className="admin-navitem-hint">{hint}</span>
              </span>
            </button>
          ))}
        </nav>
        <Card className="pop pop-1" eyebrow={`0${idx + 1} · ${ADMIN_SECTIONS[idx][1]}`} title={copy}
          right={needsSave && (
            <div className="row" style={{ gap: 8 }}>
              {!saved && <span className="t-faint" style={{ fontSize: 11.5 }}>有未保存修改</span>}
              <button className="btn btn-sm btn-primary" disabled={saved} onClick={save}>保存草稿</button>
            </div>
          )}>
          {body}
        </Card>
        <div className="pop pop-2"><AdminSidebar /></div>
      </div>
    </div>
  );
}

window.AdminPage = AdminPage;
