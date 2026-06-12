// ============================================================
// AI 聊天页 — 会话 / 流式回答 / 待确认动作
// ============================================================
import React from 'react';
import { Badge, MCStore, Markdown, McIcon, PageHead, navigate, toast, useStore } from './shared';
const { useState: useCState, useRef: useCRef, useEffect: useCEffect } = React;

function StagePill({ stage, label }: any) {
  return (
    <div className="row" style={{ gap: 7, fontSize: 12, color: 'var(--ink-3)' }}>
      <span className="pulse-dot" style={{ background: 'var(--accent)' }}></span>
      {label || (stage === 'prepare' ? '已收到请求…' : stage === 'evidence' ? '读取项目证据…' : '处理中…')}
    </div>
  );
}

function PendingAction({ action, onConfirm, confirmed }: any) {
  return (
    <div className="glass-inset" style={{ marginTop: 12, padding: 13, borderColor: 'var(--warn)', borderWidth: 1 }}>
      <div className="spread">
        <span className="t-num" style={{ fontSize: 12.5, fontWeight: 650, color: 'var(--warn)' }}>{action.action}</span>
        <Badge tone={action.risk === 'high' ? 'badge-up' : 'badge-warn'}>{action.risk === 'high' ? '高风险' : '中风险'} · 需确认</Badge>
      </div>
      <dl style={{ margin: '9px 0 0', display: 'grid', gap: 4 }}>
        {Object.entries(action.payload).map(([k, v]) => (
          <div key={k} className="row" style={{ gap: 8, fontSize: 12 }}>
            <dt style={{ fontWeight: 600, color: 'var(--ink-2)', minWidth: 64 }}>{k}</dt>
            <dd style={{ margin: 0 }} className="t-num t-dim">{String(v)}</dd>
          </div>
        ))}
      </dl>
      {confirmed ? (
        <div className="badge badge-down" style={{ marginTop: 10 }}>✓ 已确认执行</div>
      ) : (
        <div className="row" style={{ marginTop: 10, gap: 6 }}>
          <button className="btn btn-sm btn-primary" onClick={onConfirm}>确认执行</button>
          <span className="t-faint" style={{ fontSize: 11.5 }}>确认前不会写入任何数据</span>
        </div>
      )}
    </div>
  );
}

function DebateRoundControl({ value, onChange }: any) {
  const ORCH = window.MC_DATA.COPILOT_ORCHESTRATION;
  const max = ORCH.round_templates.length;
  return (
    <div className="glass-inset" style={{ padding: 13 }}>
      <div className="spread" style={{ gap: 8 }}>
        <div>
          <div className="t-eyebrow">LLM 多轮辩论</div>
          <div style={{ fontSize: 14.5, fontWeight: 700, marginTop: 4 }}>{value} 轮</div>
        </div>
        <div className="row" style={{ gap: 5 }}>
          <button className="btn btn-sm" disabled={value <= 1} onClick={() => onChange(value - 1)}>-</button>
          <button className="btn btn-sm" disabled={value >= max} onClick={() => onChange(value + 1)}>+</button>
        </div>
      </div>
      <input type="range" min="1" max={max} value={value} onChange={(e) => onChange(Number(e.target.value))}
        style={{ width: '100%', marginTop: 10, accentColor: 'var(--accent)' }} />
      <div className="grid" style={{ gap: 6, marginTop: 10 }}>
        {ORCH.round_templates.slice(0, value).map(([label, note]) => (
          <div key={label} className="row" style={{ gap: 8, alignItems: 'flex-start', fontSize: 12.3, lineHeight: 1.45 }}>
            <Badge tone="badge-accent">{label}</Badge>
            <span className="t-dim">{note}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ModeChoice({ item, active, onSelect }: any) {
  return (
    <button
      type="button"
      onClick={() => onSelect(item.id)}
      className="glass-inset"
      style={{
        padding: 12,
        textAlign: 'left',
        borderColor: active ? 'rgba(0,122,255,.48)' : 'var(--hairline-soft)',
        background: active ? 'rgba(0,122,255,.08)' : 'rgba(255,255,255,.52)',
        boxShadow: active ? 'inset 0 0 0 1px rgba(0,122,255,.18)' : 'none',
        cursor: 'pointer',
      }}
      aria-pressed={active}
    >
      <div className="spread" style={{ gap: 8, alignItems: 'flex-start' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 750 }}>{item.title}</div>
          <div className="t-faint" style={{ fontSize: 11.3, marginTop: 2 }}>{item.summary}</div>
        </div>
        <Badge tone={active ? 'badge-accent' : 'badge-dim'}>{item.badge}</Badge>
      </div>
      <div className="grid" style={{ gap: 5, marginTop: 10, fontSize: 11.7, lineHeight: 1.45 }}>
        <div><span className="t-eyebrow" style={{ letterSpacing: 0 }}>适合</span><span className="t-dim"> {item.bestFor}</span></div>
        <div><span className="t-eyebrow" style={{ letterSpacing: 0 }}>输出</span><span className="t-dim"> {item.output}</span></div>
        <div><span className="t-eyebrow" style={{ letterSpacing: 0 }}>影响</span><span className="t-dim"> {item.impact}</span></div>
      </div>
    </button>
  );
}

function CopilotOrchestrationPanel({ mode, onModeChange, debateRounds, onDebateRounds }: any) {
  const ORCH = window.MC_DATA.COPILOT_ORCHESTRATION;
  const modeOptions = [
    {
      id: 'general',
      title: '通用助手',
      badge: '快问快答',
      summary: '处理临时问题,只给可确认建议。',
      bestFor: '问个股怎么看、查证据、加自选/小动作',
      output: '即时回答 + 待确认动作',
      impact: '不重写长期标签,确认后才进入案卷',
      current: '当前会走:证据检索、skills 编排、多轮辩论、待确认动作。',
    },
    {
      id: 'long_term_team',
      title: '长期研究团队',
      badge: '慢变量复核',
      summary: '让多分析师围绕同一标的做完整研究。',
      bestFor: '长期标签、仓位约束、质量/景气/资金流复核',
      output: '多角色结论 + 长期标签建议',
      impact: '会影响个股案卷里的长期研究与纪律边界',
      current: '当前会走:长期研究团队、质量/景气/资金流、风险经理裁定。',
    },
  ];
  const activeMode = modeOptions.find((item) => item.id === mode) || modeOptions[0];
  return (
    <aside style={{ borderLeft: '1px solid var(--hairline-soft)', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div className="card-head">
        <div>
          <div className="t-eyebrow">Research Run</div>
          <div className="t-title" style={{ fontSize: 14 }}>研究编排</div>
        </div>
        <Badge tone="badge-accent">{ORCH.target.symbol}</Badge>
      </div>
      <div className="scroll-thin" style={{ padding: 14, display: 'grid', gap: 12, overflowY: 'auto' }}>
        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow" style={{ marginBottom: 7 }}>运行模式</div>
          <div className="grid" style={{ gap: 8 }}>
            {modeOptions.map((item) => (
              <ModeChoice key={item.id} item={item} active={mode === item.id} onSelect={onModeChange} />
            ))}
          </div>
          <div className="glass-inset" style={{ marginTop: 9, padding: '9px 10px', borderStyle: 'dashed' }}>
            <div className="row" style={{ gap: 7, fontSize: 11.8, lineHeight: 1.45 }}>
              <McIcon name="agents" size={13} />
              <span className="t-dim">{activeMode.current}</span>
            </div>
          </div>
        </div>

        <DebateRoundControl value={debateRounds} onChange={onDebateRounds} />

        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">执行链路</div>
          <div className="grid" style={{ gap: 8, marginTop: 10 }}>
            {ORCH.stages.map(([label, note, kind], i) => (
              <div key={label} className="row" style={{ gap: 9, alignItems: 'flex-start' }}>
                <span className="t-num" style={{ width: 18, height: 18, borderRadius: 999, background: 'var(--chip-bg)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flex: 'none', fontSize: 10.5 }}>{i + 1}</span>
                <div style={{ minWidth: 0 }}>
                  <div className="spread" style={{ gap: 6 }}>
                    <span style={{ fontSize: 12.5, fontWeight: 650 }}>{label}</span>
                    <Badge tone={kind === 'pending' ? 'badge-warn' : kind === 'llm' ? 'badge-accent' : 'badge-dim'}>{kind}</Badge>
                  </div>
                  <div className="t-faint" style={{ fontSize: 11.5, lineHeight: 1.45, marginTop: 2 }}>{note}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">Skills</div>
          <div className="grid" style={{ gap: 7, marginTop: 10 }}>
            {ORCH.skills.map((s) => (
              <div key={s.name} className="spread" style={{ gap: 8 }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 650 }}>{s.label}</div>
                  <div className="t-num t-faint" style={{ fontSize: 10.8, marginTop: 1 }}>{s.name}</div>
                </div>
                <Badge tone={s.status === 'active' ? 'badge-down' : 'badge-warn'}>{s.boundary}</Badge>
              </div>
            ))}
          </div>
        </div>

        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">影响到哪里</div>
          <div className="grid" style={{ gap: 7, marginTop: 10 }}>
            {ORCH.outputs.map(([label, note, route]) => (
              <button key={label} className="navlink" style={{ justifyContent: 'space-between', border: '1px solid var(--hairline-soft)' }} onClick={() => navigate(route)}>
                <span style={{ minWidth: 0 }}>
                  <span style={{ display: 'block', fontWeight: 650 }}>{label}</span>
                  <span className="t-faint" style={{ display: 'block', fontSize: 11.2, marginTop: 2 }}>{note}</span>
                </span>
                <McIcon name="external" size={14} />
              </button>
            ))}
          </div>
        </div>
      </div>
    </aside>
  );
}

function buildResearchRunReply(rounds) {
  const ORCH = window.MC_DATA.COPILOT_ORCHESTRATION;
  const roundText = ORCH.round_templates.slice(0, rounds)
    .map(([label, note]) => `- **${label}**:${note}`)
    .join('\n');
  return `## 研究编排运行结果

目标: **${ORCH.target.name} ${ORCH.target.symbol}**
运行模式: 证据检索 → skills 编排 → LLM ${rounds} 轮辩论 → 风险经理 → 个股案卷落点

### 本次参与 skills
- 来源审计:检查新闻/公告/行业材料的证据等级
- 个股案卷:读取裁决、价格、持仓、历史复盘
- 辩论总监:生成多空议题并控制辩论轮数
- 风险经理:只做降级、拦截、仓位约束
- 记忆召回:只读取 trusted memory,不自动写入

### LLM 辩论摘要
${roundText}

### 对个股研究的影响
- 更新 **副驾驶影子意见**,但不覆盖官方裁决
- 生成新的证伪问题,进入个股案卷
- 若需要写入记忆,只形成候选,等待人工确认

**结论:** 300308 趋势与产业景气仍强,但估值和拥挤度要求维持小仓纪律;不建议追高加仓。`;
}

export function ChatPage() {
  const [state, setStore] = useStore();
  const { sessions } = state;
  const [mode, setMode] = useCState('general');
  const [activeId, setActiveId] = useCState(sessions[0]?.id || null);
  const [input, setInput] = useCState('');
  const [busy, setBusy] = useCState(false);
  const [confirmArchive, setConfirmArchive] = useCState<any>(null);
  const [confirmedActs, setConfirmedActs] = useCState<any>({});
  const scrollRef = useCRef<any>(null);
  const active = sessions.find((s) => s.id === activeId);
  const debateRounds = state.runtime?.debate_rounds || 3;

  function updateDebateRounds(v) {
    const next = Math.max(1, Math.min(5, v));
    setStore((st) => ({ runtime: { ...st.runtime, debate_rounds: next } }));
  }

  useCEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [active?.messages?.length, busy, sessions]);

  // live 模式:后端会话的消息懒加载(messages === null 表示未加载)
  useCEffect(() => {
    if (active && active.messages === null && window.MC_LIVE) {
      patchSession(active.id, (s) => ({ ...s, messages: [] }));
      window.MC_LIVE.loadChatMessages(active.id)
        .then((msgs) => patchSession(active.id, (s) => ({ ...s, messages: msgs })))
        .catch(() => {});
    }
  }, [active?.id]);

  function patchSession(id, fn) {
    MCStore.set((st) => ({ sessions: st.sessions.map((s) => (s.id === id ? fn(s) : s)) }));
  }

  function newSession() {
    if (window.MC_LIVE && window.MC_LIVE.isLive()) {
      window.MC_LIVE.createSession({ title: '新对话', mode })
        .then((s) => {
          MCStore.set((st) => ({ sessions: [{ id: s.id, title: s.title || '新对话', mode, last_message: '', messages: [] }, ...st.sessions] }));
          setActiveId(s.id);
        })
        .catch((e) => toast(`新建会话失败:${e?.message || '后端错误'}`));
      return;
    }
    const id = `s${Date.now()}`;
    MCStore.set((st) => ({ sessions: [{ id, title: '新对话', mode, last_message: '', messages: [] }, ...st.sessions] }));
    setActiveId(id);
  }

  function archive(id) {
    const local = () => {
      MCStore.set((st) => ({ sessions: st.sessions.filter((s) => s.id !== id) }));
      setConfirmArchive(null);
      if (activeId === id) {
        const rest = MCStore.get().sessions;
        setActiveId(rest[0]?.id || null);
      }
      toast('会话已归档');
    };
    if (window.MC_LIVE && window.MC_LIVE.isLive()) {
      window.MC_LIVE.archiveSession(id).then(local).catch((e) => toast(`归档失败:${e?.message || '后端错误'}`));
      return;
    }
    local();
  }

  // live 模式真实发送:SSE 流式回答,阶段提示与 token 都来自后端
  async function sendLive(text) {
    setInput('');
    setBusy(true);
    let sid = activeId;
    const isLocalId = (v) => typeof v === 'string' && v.startsWith('s');
    try {
      if (!sid || isLocalId(sid)) {
        const s = await window.MC_LIVE.createSession({ title: text.slice(0, 14), mode });
        MCStore.set((st) => ({ sessions: [{ id: s.id, title: s.title || text.slice(0, 14), mode, last_message: '', messages: [] }, ...st.sessions.filter((x) => x.id !== sid)] }));
        sid = s.id;
        setActiveId(sid);
      }
    } catch (e) { /* 会话创建失败时按无会话发送 */ }

    const history = (MCStore.get().sessions.find((s) => s.id === sid)?.messages || [])
      .filter((m) => m.role === 'user' ? m.content : m.answer)
      .slice(-8)
      .map((m) => ({ role: m.role, content: m.role === 'user' ? m.content : m.answer }));

    patchSession(sid, (s) => ({
      ...s,
      title: s.title === '新对话' ? text.slice(0, 14) : s.title,
      last_message: text,
      messages: [...(s.messages || []), { role: 'user', content: text }, { role: 'assistant', answer: '', _stage: 'prepare' }],
    }));

    const patchLast = (fn) => patchSession(sid, (s) => {
      const msgs = (s.messages || []).slice();
      if (msgs.length) msgs[msgs.length - 1] = fn(msgs[msgs.length - 1]);
      return { ...s, messages: msgs };
    });

    let acc = '';
    try {
      const done = await window.MC_LIVE.sendChat(
        { message: text, mode, session_id: sid != null ? String(sid) : null, history },
        {
          onRunning: () => patchLast((m) => ({ ...m, _stage: 'running', _stageLabel: mode === 'long_term_team' ? '长期研究团队分析中…' : '处理中…' })),
          onEvidence: () => patchLast((m) => ({ ...m, _stage: 'evidence', _stageLabel: '读取项目证据…' })),
          onToken: (t) => { acc += t; patchLast((m) => ({ ...m, answer: acc, _stage: 'streaming' })); },
        }
      );
      const answer = (done && done.answer) || acc || '(后端未返回内容)';
      patchSession(sid, (s) => {
        const msgs = (s.messages || []).slice();
        msgs[msgs.length - 1] = {
          role: 'assistant', answer, _stage: 'done',
          used_resources: (done && done.used_resources) || [],
          pending_action: (done && done.pending_action) || null,
        };
        return { ...s, messages: msgs, last_message: answer.slice(0, 40).replace(/[#*|\n]/g, ' ').trim() };
      });
    } catch (err) {
      patchLast((m) => ({ ...m, _stage: 'done', answer: `请求失败:${(err as any)?.message || '后端错误'}` }));
    }
    setBusy(false);
  }

  function send(e) {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    if (window.MC_LIVE && window.MC_LIVE.isLive()) { sendLive(text); return; }
    let sid = activeId;
    if (!sid) {
      sid = `s${Date.now()}`;
      MCStore.set((st) => ({ sessions: [{ id: sid, title: text.slice(0, 14), mode, last_message: '', messages: [] }, ...st.sessions] }));
      setActiveId(sid);
    }
    setInput('');
    setBusy(true);
    const D = window.MC_DATA;
    const script = mode === 'long_term_team'
      ? { reply: '## 长期研究团队 · 运行结果\n\n已对 **300308 中际旭创** 完成慢变量复核:\n\n| 分析师 | 结论 | 分数 |\n|---|---|---|\n| 质量(Piotroski) | 盈利质量高位稳定 | 86 |\n| 景气 | AI 光模块仍强,边际变钝 | 91 |\n| 资金流(QFII) | 未见一致减仓 | 中性 |\n| 风险经理 | 估值分位 85%+,约束仓位 | ⚠ |\n\n**长期标签:值得持有(+72.5),有效至 2026-06-22。** 标签已通过质量门,可约束官方动作。', resources: ['long_term/300308', 'fundamentals', 'qfii_holdings'] }
      : (/研究|分析|怎么看/i.test(text)
        ? { reply: buildResearchRunReply(debateRounds), resources: ['skill:source_audit', 'skill:stock_dossier', 'skill:debate_director', 'skill:risk_manager', 'memory/context'] }
        : (D.CHAT_SCRIPTS.find((s) => s.match.test(text)) || { reply: D.CHAT_FALLBACK, resources: [] }));

    patchSession(sid, (s) => ({
      ...s,
      title: s.title === '新对话' ? text.slice(0, 14) : s.title,
      last_message: text,
      messages: [...s.messages, { role: 'user', content: text }, { role: 'assistant', answer: '', _stage: 'prepare' }],
    }));

    const stages: [string, string, number][] = [['running', mode === 'long_term_team' ? '长期研究团队分析中…' : '处理中…', 500], ['evidence', '读取项目证据…', 1050]];
    stages.forEach(([stage, label, at]) => {
      setTimeout(() => patchSession(sid, (s) => {
        const msgs = s.messages.slice();
        msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], _stage: stage, _stageLabel: label };
        return { ...s, messages: msgs };
      }), at);
    });

    // 模拟 token 流(单一 interval + 时间戳推进,避免嵌套 timeout 被限流)
    const full = script.reply;
    const startAt = 1500;
    const charsPerSec = 180;
    setTimeout(() => {
      const t0 = Date.now();
      const timer = setInterval(() => {
        const i = Math.min(full.length, Math.ceil(((Date.now() - t0) / 1000) * charsPerSec));
        patchSession(sid, (s) => {
          const msgs = s.messages.slice();
          const lastMsg = { ...msgs[msgs.length - 1], answer: full.slice(0, i), _stage: 'streaming' };
          if (i >= full.length) {
            lastMsg._stage = 'done';
            lastMsg.used_resources = script.resources;
            if (script.action) lastMsg.pending_action = { ...script.action, id: `${script.action.id}-${Date.now()}` };
          }
          msgs[msgs.length - 1] = lastMsg;
          return { ...s, messages: msgs, last_message: i >= full.length ? full.slice(0, 40).replace(/[#*|\n]/g, ' ').trim() : s.last_message };
        });
        if (i >= full.length) { clearInterval(timer); setBusy(false); }
      }, 50);
    }, startAt);
  }

  function confirmAction(act) {
    if (window.MC_LIVE && window.MC_LIVE.isLive() && act.id != null) {
      window.MC_LIVE.confirmAction(act.id)
        .then(() => { setConfirmedActs((m) => ({ ...m, [act.id]: true })); toast(`已执行 ${act.action}`); })
        .catch((e) => toast(`执行失败:${e?.message || '后端错误'}`));
      return;
    }
    setConfirmedActs((m) => ({ ...m, [act.id]: true }));
    if (act.action === 'watchlist.add') {
      const p = act.payload;
      if (!MCStore.get().watchlist.some((w) => w.symbol === p.symbol)) {
        MCStore.set((st) => ({ watchlist: [...st.watchlist, { symbol: p.symbol, name: p.name, market: p.market, industry: '待标注', latest_signal: null }] }));
      }
      toast(`已执行 watchlist.add:${p.name} 加入自选池`);
    } else if (act.action === 'position.add') {
      const p = act.payload;
      const px = window.MC_DATA.PRICES[p.symbol];
      const latest = px ? px[px.length - 1].close : p.avg_cost;
      MCStore.set((st) => ({ positions: [...st.positions, { id: Date.now(), symbol: p.symbol, name: (st.watchlist.find((w) => w.symbol === p.symbol) || {}).name || p.symbol, market: p.market, status: 'open', quantity: p.quantity, avg_cost: p.avg_cost, latest_price: latest, stop_loss: +(latest * 0.93).toFixed(2), take_profit: +(latest * 1.12).toFixed(2), entry_date: '2026-06-11' }] }));
      toast('已执行 position.add:持仓已记录');
    } else {
      toast(`已执行 ${act.action}`);
    }
  }

  return (
    <div className="grid" style={{ gap: 14 }}>
      <PageHead eyebrow="Research Copilot" title="研究副驾驶"
        desc="副驾驶不是普通聊天窗口,而是一条可调度的研究运行链:检索证据、调用 skills、组织多轮辩论,再把影子结论落到个股案卷。" />

      <section className="glass pop" style={{ display: 'grid', gridTemplateColumns: '264px minmax(0, 1fr) 330px', minHeight: 680, overflow: 'hidden' }} data-grid="chat-cols" data-tour="chat-shell">
        <aside style={{ borderRight: '1px solid var(--hairline-soft)', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div className="card-head">
            <div>
              <div className="t-eyebrow">Windows</div>
              <div className="t-title" style={{ fontSize: 14 }}>对话窗口</div>
            </div>
            <button className="btn btn-sm btn-primary" onClick={newSession}>新建</button>
          </div>
          <div className="scroll-thin" style={{ overflowY: 'auto', padding: 0, flex: 1 }}>
            {sessions.length === 0 && <div className="empty" style={{ margin: 8 }}>暂无历史窗口。点「新建」开始对话。</div>}
            {sessions.map((s, i) => (
              <div key={s.id} style={{
                padding: '12px 16px', cursor: 'pointer',
                borderLeft: activeId === s.id ? '3px solid var(--accent)' : '3px solid transparent',
                borderBottom: i < sessions.length - 1 ? '1px solid var(--hairline-soft)' : 'none',
                background: activeId === s.id ? 'var(--accent-soft)' : 'transparent',
                transition: 'background 0.15s',
              }} onClick={() => setActiveId(s.id)}>
                <div style={{ fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.title}</div>
                <div className="t-faint" style={{ fontSize: 11.5, marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.last_message || '空窗口'}</div>
                <div className="row" style={{ marginTop: 7, gap: 5 }} onClick={(e) => e.stopPropagation()}>
                  {confirmArchive === s.id ? (
                    <React.Fragment>
                      <button className="btn btn-sm btn-danger" onClick={() => archive(s.id)}>确认归档</button>
                      <button className="btn btn-sm btn-quiet" onClick={() => setConfirmArchive(null)}>取消</button>
                    </React.Fragment>
                  ) : (
                    <button className="btn btn-sm btn-quiet" style={{ fontSize: 11.5, padding: '2px 9px' }} onClick={() => setConfirmArchive(s.id)}>归档</button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </aside>

        <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, minWidth: 0 }}>
          <div ref={scrollRef} className="scroll-thin" style={{ flex: 1, overflowY: 'auto', padding: 18, display: 'grid', gap: 12, alignContent: 'start' }}>
            {(!active || (active.messages || []).length === 0) && (
              <div className="glass-inset" style={{ padding: '13px 16px', fontSize: 13, lineHeight: 1.65, color: 'var(--ink-2)', borderColor: 'var(--accent)', background: 'var(--accent-soft)' }}>
                每个窗口只继承本窗口上下文;窗口外历史不会进入对话记忆。AI 仍可调取明仓的自选股、持仓、信号、复盘和研究资源。
                <div className="row" style={{ marginTop: 10, gap: 6, flexWrap: 'wrap' }}>
                  {['300308 怎么看', '持仓风险如何', '添加自选 002475', '今天复盘说了什么'].map((q) => (
                    <button key={q} className="btn btn-sm" onClick={() => setInput(q)}>{q}</button>
                  ))}
                </div>
              </div>
            )}
            {(active?.messages || []).map((m, i) => (
              <div key={i} style={{
                maxWidth: '85%', justifySelf: m.role === 'user' ? 'end' : 'start',
                padding: '11px 15px', borderRadius: 18, fontSize: 13.5, lineHeight: 1.6,
                background: m.role === 'user' ? 'var(--accent)' : 'var(--chip-bg)',
                color: m.role === 'user' ? '#fff' : 'var(--ink)',
                border: m.role === 'user' ? 'none' : '1px solid var(--hairline-soft)',
                borderBottomRightRadius: m.role === 'user' ? 6 : 18,
                borderBottomLeftRadius: m.role === 'user' ? 18 : 6,
              }}>
                {m.role === 'user' ? m.content : (
                  <div>
                    {!m.answer && m._stage && m._stage !== 'done' && <StagePill stage={m._stage} label={m._stageLabel} />}
                    {m.answer && <Markdown text={m.answer} />}
                    {m.used_resources?.length > 0 && (
                      <div className="t-num t-faint" style={{ fontSize: 10.5, marginTop: 8, opacity: 0.8 }}>resources: {m.used_resources.join(', ')}</div>
                    )}
                    {m.pending_action && (
                      <PendingAction action={m.pending_action} confirmed={confirmedActs[m.pending_action.id]} onConfirm={() => confirmAction(m.pending_action)} />
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
          <form onSubmit={send} style={{ borderTop: '1px solid var(--hairline-soft)', padding: 14 }}>
            <div className="row" style={{ gap: 8 }}>
              <input className="field" style={{ flex: 1, borderRadius: 999, padding: '10px 16px' }} value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={mode === 'long_term_team' ? '输入:研究 300308' : '向明仓提问,或下达项目操作'} />
              <button className="btn btn-primary" disabled={busy || !input.trim()} type="submit" style={{ padding: '9px 20px' }}>{busy ? '思考中…' : '发送'}</button>
            </div>
          </form>
        </div>
        <CopilotOrchestrationPanel mode={mode} onModeChange={setMode} debateRounds={debateRounds} onDebateRounds={updateDebateRounds} />
      </section>
    </div>
  );
}

window.ChatPage = ChatPage;
