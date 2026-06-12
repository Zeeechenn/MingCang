// ============================================================
// 新手引导 — 首次运行向导 + 功能导览(逐步高亮)
// ============================================================
import React from 'react';
import { Badge, navigate } from './shared';
const { useState: useOState, useEffect: useOEffect, useRef: useORef } = React;

const WIZ_KEY = 'mc_proto_wizard_done_v1';

const WIZ_MODES = [
  { id: 'research', label: 'A股研究', hint: '每日信号、多空辩论、深度研究' },
  { id: 'review', label: '复盘', hint: '每日 / 长期复盘生成与历史回溯' },
  { id: 'watchlist', label: '自选跟踪', hint: '关注池管理与标的走势跟踪' },
  { id: 'demo', label: '只看 Demo', hint: '用示例数据了解系统，不录入真实数据' },
];

function StepDots({ current, total }: any) {
  return (
    <div className="row" style={{ gap: 5 }}>
      {Array.from({ length: total }, (_, i) => (
        <div key={i} style={{
          height: 6, borderRadius: 999, transition: 'all 0.3s',
          width: i === current ? 18 : 6,
          background: i <= current ? 'var(--accent)' : 'var(--hairline)',
        }}></div>
      ))}
    </div>
  );
}

export function FirstRunWizard({ onDone, onStartTour }: any) {
  const [step, setStep] = useOState(0);
  const [mode, setMode] = useOState('research');
  const [agreed, setAgreed] = useOState(false);
  const TOTAL = 5;

  function finish(startTour) {
    try { localStorage.setItem(WIZ_KEY, '1'); } catch (e) { /* ignore */ }
    onDone();
    if (startTour) onStartTour();
  }

  const steps = [
    <div key="s1">
      <h2 className="t-title" style={{ margin: 0, fontSize: 19 }}>欢迎使用明仓</h2>
      <p className="t-dim" style={{ margin: '8px 0 16px', fontSize: 13.5, lineHeight: 1.6 }}>
        明仓是本地优先的 A股研究决策系统:盘后信号、多空辩论、长期标签、复盘与记忆，全部留在你自己的机器上。先选一个最符合你的使用模式，随时可在配置页切换。
      </p>
      <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        {WIZ_MODES.map((m) => (
          <button key={m.id} className="glass-inset" style={{
            padding: '13px 15px', textAlign: 'left', cursor: 'pointer', font: 'inherit', color: 'inherit',
            borderColor: mode === m.id ? 'var(--accent)' : undefined,
            background: mode === m.id ? 'var(--accent-soft)' : undefined,
          }} onClick={() => setMode(m.id)}>
            <div style={{ fontSize: 13.5, fontWeight: 650 }}>{m.label}</div>
            <div className="t-faint" style={{ fontSize: 12, marginTop: 3 }}>{m.hint}</div>
          </button>
        ))}
      </div>
    </div>,
    <div key="s2">
      <h2 className="t-title" style={{ margin: 0, fontSize: 19 }}>导入或创建 3 个关注标的</h2>
      <p className="t-dim" style={{ margin: '8px 0 14px', fontSize: 13.5, lineHeight: 1.6 }}>
        信号围绕自选池生成。两种添加方式，添加后系统会在下次收盘后自动生成信号:
      </p>
      <div className="grid" style={{ gap: 8 }}>
        <div className="glass-inset" style={{ padding: '12px 15px' }}>
          <div style={{ fontSize: 13, fontWeight: 650 }}>方式一:脉冲页手动添加</div>
          <div className="t-faint" style={{ fontSize: 12.5, marginTop: 3 }}>脉冲页 → 自选股管理 → 点击「＋ 添加标的」，支持 A股 / 港股 / 美股搜索</div>
        </div>
        <div className="glass-inset" style={{ padding: '12px 15px' }}>
          <div style={{ fontSize: 13, fontWeight: 650 }}>方式二:AI 对话导入</div>
          <div className="t-faint" style={{ fontSize: 12.5, marginTop: 3 }}>AI 对话页输入 <code style={{ fontFamily: 'var(--font-mono)' }}>添加自选 300308</code>，确认后写入</div>
        </div>
      </div>
    </div>,
    <div key="s3">
      <h2 className="t-title" style={{ margin: 0, fontSize: 19 }}>研究是只读的，写入需要你确认</h2>
      <p className="t-dim" style={{ margin: '8px 0 14px', fontSize: 13.5, lineHeight: 1.6 }}>
        明仓的边界设计:
      </p>
      <div className="grid" style={{ gap: 8 }}>
        {[
          ['只读查询', '信号、证据链、新闻、数据健康随便看，不会改任何状态', 'badge-down'],
          ['需确认操作', '加自选、记持仓、写记忆、刷新研究 — AI 只生成候选动作，你确认后才执行', 'badge-warn'],
          ['永不发生', '自动下单、接券商、用研究结论替代你的决策', 'badge-up'],
        ].map(([t, d, tone]) => (
          <div key={t} className="glass-inset row" style={{ padding: '11px 14px', gap: 12, alignItems: 'flex-start' }}>
            <Badge tone={tone}>{t}</Badge>
            <span className="t-dim" style={{ fontSize: 12.5, lineHeight: 1.55 }}>{d}</span>
          </div>
        ))}
      </div>
    </div>,
    <div key="s4">
      <h2 className="t-title" style={{ margin: 0, fontSize: 19 }}>示例数据帮你理解界面</h2>
      <p className="t-dim" style={{ margin: '8px 0 14px', fontSize: 13.5, lineHeight: 1.6 }}>
        当前界面预置了一套示例自选池、信号、持仓和复盘(标的为 300308 中际旭创等)。真实数据生成后会自动替换。复盘页已有完整的每日 / 长期复盘示例，可以先去感受系统的输出形态。
      </p>
      <div className="glass-inset" style={{ padding: '12px 15px', fontSize: 12.5, lineHeight: 1.6, color: 'var(--ink-2)' }}>
        建议路径:<b style={{ color: 'var(--ink)' }}>脉冲页</b>看今日决策 → 点进<b style={{ color: 'var(--ink)' }}>单股详情</b>看证据链 → <b style={{ color: 'var(--ink)' }}>复盘页</b>读完整报告 → <b style={{ color: 'var(--ink)' }}>AI 对话</b>试试「300308 怎么看」。
      </div>
    </div>,
    <div key="s5">
      <h2 className="t-title" style={{ margin: 0, fontSize: 19 }}>免责声明</h2>
      <p className="t-dim" style={{ margin: '8px 0 14px', fontSize: 13.5, lineHeight: 1.65 }}>
        明仓输出的信号、标签、复盘与对话内容均为<b style={{ color: 'var(--ink)' }}>研究记录与决策辅助</b>，不构成投资建议;系统不接入券商、不自动交易。投资有风险，决策责任始终在你。
      </p>
      <label className="glass-inset row" style={{ padding: '12px 15px', gap: 10, cursor: 'pointer' }}>
        <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} style={{ accentColor: 'var(--accent)', width: 16, height: 16 }} />
        <span style={{ fontSize: 13 }}>我已了解:这是研究工具，不是投资建议</span>
      </label>
    </div>,
  ];

  return (
    <div className="scrim">
      <div className="modal glass" style={{ background: 'var(--glass-strong)', padding: '24px 26px' }}>
        <div className="spread" style={{ marginBottom: 18 }}>
          <div className="row" style={{ gap: 9 }}>
            <div style={{ width: 26, height: 26, borderRadius: 8, background: 'var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 700, fontSize: 13 }}>仓</div>
            <span className="t-eyebrow">首次运行 · {step + 1} / {TOTAL}</span>
          </div>
          <StepDots current={step} total={TOTAL} />
        </div>
        {steps[step]}
        <div className="spread" style={{ marginTop: 22 }}>
          <button className="btn btn-quiet btn-sm" onClick={() => finish(false)}>跳过</button>
          <div className="row" style={{ gap: 8 }}>
            {step > 0 && <button className="btn" onClick={() => setStep(step - 1)}>上一步</button>}
            {step < TOTAL - 1 ? (
              <button className="btn btn-primary" onClick={() => setStep(step + 1)}>继续</button>
            ) : (
              <button className="btn btn-primary" disabled={!agreed} onClick={() => finish(true)}>完成并开始导览</button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------- 功能导览 ----------
const TOUR_STEPS = [
  { route: '/', target: 'nav', title: '浮动导航', body: '八个工作区:明仓终端、今日裁决、个股案卷、复盘案卷、研究副驾驶、持仓纪律、来源健康、治理台。右侧可切换浅色 / 深色，随时点「导览」回到这里。' },
  { route: '/pulse', target: 'today-call', title: '今日决策', body: '系统从自选池里挑出最强信号:综合评分(-100~+100)、技术 / 情感分项、止损止盈参考，以及研究总监的多空裁决。' },
  { route: '/pulse', target: 'signal-grid', title: '信号横条', body: '自选池每只标的的最新信号一览。红色徽章偏多、绿色偏空(A股习惯)。点卡片进入单股详情。' },
  { route: '/pulse', target: 'watchlist', title: '自选股管理', body: '在这里添加 / 移除关注标的，支持按市场和信号筛选。添加后下次收盘自动生成信号。' },
  { route: '/stock/300308', target: 'chart', title: '单股主图', body: '120 日价格走势，虚线是系统计算的止损 / 止盈参考线。鼠标悬停可查看每日明细。' },
  { route: '/stock/300308', target: 'copilot', title: '双轨影子决策', body: 'LLM 副驾驶给出独立的影子意见，与官方规则并行展示 — 它可以反对官方信号，但永远不覆盖它。' },
  { route: '/stock/300308', target: 'evidence', title: '证据链', body: '每个信号都可追溯:决策运行、新闻审计、风控检查、反穿越校验。这是明仓「证据优先」的核心。' },
  { route: '/positions', target: 'position-form', title: '持仓记录', body: '记录真实或模拟持仓。明仓不接券商:平仓、止损都只是记录与提醒，不会真实下单。' },
  { route: '/reports', target: 'dossier-index', title: '复盘案卷', body: '证据来源、复盘记录和记忆沉淀已合并在这里。点击案卷条目可阅读完整 Markdown 报告并导出。' },
  { route: '/chat', target: 'chat-shell', title: 'AI 项目对话', body: '问「300308 怎么看」试试。AI 能读取项目证据;所有写入操作会生成待确认动作，确认前不执行。' },
  { route: '/health', target: 'provider-chains', title: '数据健康', body: '每个市场的数据提供商回退链、新鲜度策略和告警。数据可信是信号可信的前提。' },
  { route: '/admin', target: 'admin-nav', title: '配置中心', body: '权重、阈值、仓位规则、调度、熔断开关、记忆管理和 LLM 成本都在这里。修改保存为草稿，下次决策运行生效。导览结束，开始探索吧!' },
];

export function Tour({ onClose }: any) {
  const [idx, setIdx] = useOState(0);
  const [rect, setRect] = useOState<any>(null);
  const step = TOUR_STEPS[idx];

  useOEffect(() => {
    let cancelled = false;
    navigate(step.route);
    const tryFind = (attempt) => {
      if (cancelled) return;
      const el = document.querySelector(`[data-tour="${step.target}"]`);
      if (!el) { if (attempt < 12) setTimeout(() => tryFind(attempt + 1), 120); return; }
      const r = el.getBoundingClientRect();
      const top = r.top + window.scrollY;
      window.scrollTo({ top: Math.max(0, top - 130), behavior: 'smooth' });
      setTimeout(() => {
        if (cancelled) return;
        const r2 = el.getBoundingClientRect();
        setRect({ top: r2.top + window.scrollY - 6, left: r2.left + window.scrollX - 6, width: r2.width + 12, height: r2.height + 12 });
      }, 420);
    };
    setRect(null);
    setTimeout(() => tryFind(0), 80);
    return () => { cancelled = true; };
  }, [idx]);

  if (!rect) return <div style={{ position: 'fixed', inset: 0, zIndex: 94, background: 'rgba(15,18,28,0.25)' }}></div>;

  const below = rect.top + rect.height + 16;
  const cardTop = below + 330 > window.scrollY + window.innerHeight && rect.top - 220 > window.scrollY ? rect.top - 200 : below;
  const cardLeft = Math.min(Math.max(12, rect.left), Math.max(12, window.innerWidth - 348));

  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 94, pointerEvents: 'none' }}>
      <div className="tour-ring" style={{ top: rect.top, left: rect.left, width: rect.width, height: rect.height }}></div>
      <div className="tour-card glass" style={{ top: cardTop, left: cardLeft, background: 'var(--glass-strong)', padding: '16px 18px', pointerEvents: 'auto' }}>
        <div className="spread">
          <Badge tone="badge-accent">{idx + 1} / {TOUR_STEPS.length}</Badge>
          <button className="btn btn-sm btn-quiet" onClick={onClose}>结束导览</button>
        </div>
        <h3 className="t-title" style={{ margin: '10px 0 0', fontSize: 15 }}>{step.title}</h3>
        <p className="t-dim" style={{ margin: '6px 0 0', fontSize: 12.5, lineHeight: 1.6 }}>{step.body}</p>
        <div className="spread" style={{ marginTop: 14 }}>
          <button className="btn btn-sm" disabled={idx === 0} onClick={() => setIdx(idx - 1)}>上一步</button>
          {idx < TOUR_STEPS.length - 1 ? (
            <button className="btn btn-sm btn-primary" onClick={() => setIdx(idx + 1)}>下一步</button>
          ) : (
            <button className="btn btn-sm btn-primary" onClick={onClose}>完成</button>
          )}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { FirstRunWizard, Tour, MC_WIZ_KEY: WIZ_KEY });
