// ============================================================
// 新手引导 — 三步首次运行向导 + 十个顶层工作区导览
// ============================================================
import React from 'react';
import { Badge, navigate } from './shared';

const { useState: useOState, useEffect: useOEffect, useRef: useORef } = React;

export const WIZ_KEY = 'mc_proto_wizard_done_v1';
export const ONBOARDING_GOAL_KEY = 'mc_onboarding_goal_v1';

const WIZ_MODES = [
  { id: 'research', label: '研究一只股票', hint: '从个股案卷开始，查看信号、证据和长期观点', route: '/stocks' },
  { id: 'review', label: '复盘', hint: '从复盘案卷开始，回看判断、结果和可沉淀经验', route: '/reports' },
  { id: 'watchlist', label: '管理关注列表', hint: '从今日裁决开始，添加标的并查看最新信号', route: '/pulse' },
  { id: 'demo', label: '先看示例', hint: '留在明仓终端，用示例快照熟悉界面', route: '/' },
] as const;

function getFocusable(container: HTMLElement | null) {
  if (!container) return [];
  return Array.from(container.querySelectorAll<HTMLElement>(
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  ));
}

function useDialogFocus(ref: React.RefObject<HTMLElement | null>, onEscape: () => void) {
  const escapeRef = useORef(onEscape);
  escapeRef.current = onEscape;

  useOEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const focusTimer = window.setTimeout(() => ref.current?.focus(), 0);

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        escapeRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = getFocusable(ref.current);
      if (!focusable.length) {
        event.preventDefault();
        ref.current?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', onKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
      previous?.focus();
    };
  }, []);
}

function StepDots({ current, total }: { current: number; total: number }) {
  return (
    <div className="row" style={{ gap: 5 }} aria-label={`第 ${current + 1} 步，共 ${total} 步`}>
      {Array.from({ length: total }, (_, i) => (
        <span key={i} aria-hidden="true" style={{
          height: 6, borderRadius: 999, transition: 'all 0.3s',
          width: i === current ? 18 : 6,
          background: i <= current ? 'var(--accent)' : 'var(--hairline)',
        }} />
      ))}
    </div>
  );
}

export function FirstRunWizard({ onDone, onStartTour }: { onDone: () => void; onStartTour: () => void }) {
  const [step, setStep] = useOState(0);
  const [mode, setMode] = useOState<(typeof WIZ_MODES)[number]['id']>('research');
  const [agreed, setAgreed] = useOState(false);
  const dialogRef = useORef<HTMLDivElement>(null);
  const TOTAL = 3;

  function finish(startTour: boolean) {
    const selected = WIZ_MODES.find((item) => item.id === mode) || WIZ_MODES[0];
    try {
      localStorage.setItem(WIZ_KEY, '1');
      localStorage.setItem(ONBOARDING_GOAL_KEY, selected.id);
    } catch { /* ignore unavailable storage */ }
    onDone();
    navigate(selected.route);
    if (startTour) onStartTour();
  }

  useDialogFocus(dialogRef, () => onDone());

  const steps = [
    <div key="goal">
      <h2 id="first-run-title" className="t-title" style={{ margin: 0, fontSize: 20 }}>欢迎使用明仓</h2>
      <p id="first-run-desc" className="t-dim" style={{ margin: '8px 0 16px', fontSize: 13.5, lineHeight: 1.65 }}>
        先选你最想完成的一件事。完成引导后会直接打开对应页面，下次也会记住这个起点。
      </p>
      <div className="onboarding-goals" role="group" aria-label="选择开始目标">
        {WIZ_MODES.map((item) => (
          <button key={item.id} type="button" className="glass-inset onboarding-goal" aria-pressed={mode === item.id}
            onClick={() => setMode(item.id)}>
            <span style={{ fontSize: 13.5, fontWeight: 650 }}>{item.label}</span>
            <span className="t-faint" style={{ fontSize: 12, marginTop: 3 }}>{item.hint}</span>
          </button>
        ))}
      </div>
    </div>,
    <div key="truth">
      <h2 id="first-run-title" className="t-title" style={{ margin: 0, fontSize: 20 }}>先认清数据与操作边界</h2>
      <p id="first-run-desc" className="t-dim" style={{ margin: '8px 0 14px', fontSize: 13.5, lineHeight: 1.65 }}>
        导航栏始终显示数据状态：<b style={{ color: 'var(--ink)' }}>本地后端</b>是真实数据，<b style={{ color: 'var(--ink)' }}>示例快照</b>只用于体验，<b style={{ color: 'var(--ink)' }}>部分实时</b>表示有数据回退。
      </p>
      <div className="grid" style={{ gap: 8 }}>
        {[
          ['放心查看', '信号、证据、新闻和来源健康都是只读查询', 'badge-down'],
          ['确认后写入', '添加自选、记录持仓、写记忆等操作会明确要求确认', 'badge-warn'],
          ['不会发生', '明仓不接券商、不自动下单，也不会替你做投资决定', 'badge-accent'],
        ].map(([title, body, tone]) => (
          <div key={title} className="glass-inset row onboarding-boundary">
            <Badge tone={tone}>{title}</Badge>
            <span className="t-dim" style={{ fontSize: 12.5, lineHeight: 1.55 }}>{body}</span>
          </div>
        ))}
      </div>
    </div>,
    <div key="consent">
      <h2 id="first-run-title" className="t-title" style={{ margin: 0, fontSize: 20 }}>最后确认</h2>
      <p id="first-run-desc" className="t-dim" style={{ margin: '8px 0 14px', fontSize: 13.5, lineHeight: 1.65 }}>
        明仓输出的是研究记录和决策辅助，不构成投资建议。止盈止损是规则参考，最终判断和资金风险始终由你负责。
      </p>
      <label className="glass-inset row onboarding-consent">
        <input type="checkbox" checked={agreed} onChange={(event) => setAgreed(event.target.checked)} />
        <span style={{ fontSize: 13 }}>我已了解：这是研究工具，不是投资建议</span>
      </label>
      <p className="t-faint" style={{ margin: '12px 0 0', fontSize: 12.5 }}>
        你选择了：{WIZ_MODES.find((item) => item.id === mode)?.label}
      </p>
    </div>,
  ];

  return (
    <div className="scrim" role="presentation">
      <div ref={dialogRef} className="modal glass onboarding-dialog" role="dialog" aria-modal="true"
        aria-labelledby="first-run-title" aria-describedby="first-run-desc" tabIndex={-1}>
        <div className="spread" style={{ marginBottom: 18 }}>
          <div className="row" style={{ gap: 9 }}>
            <div className="onboarding-logo" aria-hidden="true">仓</div>
            <span className="t-eyebrow">首次运行 · {step + 1} / {TOTAL}</span>
          </div>
          <StepDots current={step} total={TOTAL} />
        </div>
        {steps[step]}
        <div className="onboarding-actions">
          <button type="button" className="btn btn-quiet btn-sm" onClick={() => finish(false)}>暂时跳过</button>
          <div className="row" style={{ gap: 8 }}>
            {step > 0 && <button type="button" className="btn" onClick={() => setStep(step - 1)}>上一步</button>}
            {step < TOTAL - 1 ? (
              <button type="button" className="btn btn-primary" onClick={() => setStep(step + 1)}>继续</button>
            ) : (
              <>
                <button type="button" className="btn" disabled={!agreed} onClick={() => finish(true)}>完成并导览</button>
                <button type="button" className="btn btn-primary" disabled={!agreed} onClick={() => finish(false)}>完成并进入</button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// 每个顶层导航目的地恰好对应一个导览步骤，避免新增页面后导览继续说旧话。
export const TOUR_STEPS = [
  { route: '/', title: '明仓终端', body: '用自然语言描述研究、复盘或风险问题；涉及写入时会先给出待确认动作。' },
  { route: '/daily', title: '日常', body: '按盘前、盘中、盘后和周末节奏阅读报告与待研究队列。' },
  { route: '/pulse', title: '今日裁决', body: '查看关注池的最新信号、风险线和数据来源，不把分数当成确定预测。' },
  { route: '/stocks', title: '个股案卷', body: '搜索股票，进入价格、证据、长期标签和副驾驶影子意见。' },
  { route: '/reports', title: '复盘案卷', body: '回看当时为什么这样判断、结果如何，以及哪些经验值得人工确认。' },
  { route: '/chat', title: '研究副驾驶', body: '进行连续研究对话；写入动作会停在确认边界，不会自动执行。' },
  { route: '/positions', title: '持仓纪律', body: '记录持仓、平仓和风险提醒；这里只记账，不连接券商。' },
  { route: '/memory-evolution', title: '记忆进化', body: '审阅候选经验，只有证据充分且经人工确认后才能升级。' },
  { route: '/health', title: '来源健康', body: '查看数据覆盖、新鲜度、回退链与告警，先确认数据可信再看结论。' },
  { route: '/admin', title: '治理台', body: '管理规则、调度和安全边界；高级或高风险操作需要明确确认。' },
] as const;

export function Tour({ onClose }: { onClose: () => void }) {
  const [idx, setIdx] = useOState(0);
  const [rect, setRect] = useOState<any>(null);
  const cardRef = useORef<HTMLDivElement>(null);
  const step = TOUR_STEPS[idx];

  useDialogFocus(cardRef, onClose);

  useOEffect(() => {
    let cancelled = false;
    navigate(step.route);
    const selector = `[data-screen-label="页面:${step.route === '/' ? 'home' : step.route.slice(1)}"] h1`;
    const tryFind = (attempt: number) => {
      if (cancelled) return;
      const el = document.querySelector(selector) || document.querySelector(`[data-screen-label^="页面:"] h1`);
      if (!el) {
        if (attempt < 12) window.setTimeout(() => tryFind(attempt + 1), 120);
        return;
      }
      const target = el as HTMLElement;
      const top = target.getBoundingClientRect().top + window.scrollY;
      const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
      window.scrollTo({ top: Math.max(0, top - 130), behavior: reduceMotion ? 'auto' : 'smooth' });
      window.setTimeout(() => {
        if (cancelled) return;
        const next = target.getBoundingClientRect();
        setRect({
          top: next.top + window.scrollY - 8,
          left: next.left + window.scrollX - 8,
          width: next.width + 16,
          height: next.height + 16,
        });
      }, reduceMotion ? 0 : 260);
    };
    setRect(null);
    window.setTimeout(() => tryFind(0), 60);
    return () => { cancelled = true; };
  }, [idx]);

  useOEffect(() => {
    if (rect) window.setTimeout(() => cardRef.current?.focus(), 0);
  }, [rect, idx]);

  if (!rect) {
    return <div className="tour-loading" role="status" aria-live="polite"><span className="sr-only">正在打开 {step.title}</span></div>;
  }

  const below = rect.top + rect.height + 16;
  const cardTop = below + 250 > window.scrollY + window.innerHeight && rect.top - 220 > window.scrollY ? rect.top - 190 : below;
  const cardLeft = Math.min(Math.max(12, rect.left), Math.max(12, window.innerWidth - 348));

  return (
    <div className="tour-layer" role="presentation">
      <div className="tour-ring" aria-hidden="true" style={{ top: rect.top, left: rect.left, width: rect.width, height: rect.height }} />
      <div ref={cardRef} className="tour-card glass" role="dialog" aria-modal="true"
        aria-labelledby="tour-title" aria-describedby="tour-body" tabIndex={-1}
        style={{ top: cardTop, left: cardLeft, background: 'var(--glass-strong)', padding: '16px 18px', pointerEvents: 'auto' }}>
        <div className="spread">
          <Badge tone="badge-accent">{idx + 1} / {TOUR_STEPS.length}</Badge>
          <button type="button" className="btn btn-sm btn-quiet" onClick={onClose}>结束导览</button>
        </div>
        <h3 id="tour-title" className="t-title" style={{ margin: '10px 0 0', fontSize: 15 }}>{step.title}</h3>
        <p id="tour-body" className="t-dim" style={{ margin: '6px 0 0', fontSize: 12.5, lineHeight: 1.6 }}>{step.body}</p>
        <div className="spread" style={{ marginTop: 14 }}>
          <button type="button" className="btn btn-sm" disabled={idx === 0} onClick={() => setIdx(idx - 1)}>上一步</button>
          {idx < TOUR_STEPS.length - 1 ? (
            <button type="button" className="btn btn-sm btn-primary" onClick={() => setIdx(idx + 1)}>下一步</button>
          ) : (
            <button type="button" className="btn btn-sm btn-primary" onClick={onClose}>完成</button>
          )}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { FirstRunWizard, Tour, MC_WIZ_KEY: WIZ_KEY });
