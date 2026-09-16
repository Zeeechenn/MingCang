// ============================================================
// 日常 — Stage5 single daily_panel.v1 shell
// ============================================================
import React from 'react';
import { DailyPanelCards, DailyPanelHeader } from './features/daily/DailyPanel';
import { HumanReviewPanel } from './features/daily/HumanReview';
import { getLatestM63Report } from './services/api';
import { getDailyPanelLatest, type DailyPanel } from './services/daily';
import { Badge, Markdown, PageHead, navigate } from './shared';

const { useEffect: useDailyEffect, useMemo: useDailyMemo, useState: useDailyState } = React;

const TABS = [
  ['all', '全部'],
  ['stable', 'Stable'],
  ['shadow', 'Shadow'],
  ['blocked', 'Missing / Blocked'],
];
const TAB_IDS = new Set(TABS.map(([id]) => id));

function initialDailyTab() {
  const hash = window.location.hash || '';
  const query = hash.includes('?') ? hash.slice(hash.indexOf('?') + 1) : window.location.search.slice(1);
  const requested = new URLSearchParams(query).get('tab') || 'all';
  return TAB_IDS.has(requested) ? requested : 'all';
}

function EmptyState({ text }: { text: string }) {
  return <div className="glass" style={{ padding: 18, color: 'var(--ink-3)', fontSize: 13 }}>{text}</div>;
}

function LegacyReportFallback({ active }: { active: boolean }) {
  const [report, setReport] = useDailyState<any>(null);
  useDailyEffect(() => {
    if (!active) return;
    let alive = true;
    getLatestM63Report('postmarket')
      .then((data) => { if (alive) setReport(data); })
      .catch(() => { if (alive) setReport(null); });
    return () => { alive = false; };
  }, [active]);
  if (!active) return null;
  return (
    <section className="glass pop" style={{ padding: 18, minWidth: 0 }}>
      <div className="spread" style={{ alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <div>
          <div className="t-eyebrow">Legacy fallback</div>
          <h2 className="t-title" style={{ margin: '2px 0 0' }}>M63 盘后报告</h2>
        </div>
        <Badge tone={report ? 'badge-warn' : 'badge-dim'}>{report?.as_of || 'missing'}</Badge>
      </div>
      {report ? <Markdown text={report.text || ''} /> : <EmptyState text="daily_panel 和 legacy report 均不可用。" />}
    </section>
  );
}

export function DailyPage() {
  const [tab, setTab] = useDailyState(initialDailyTab);
  const [panel, setPanel] = useDailyState<DailyPanel | null>(null);
  const [loading, setLoading] = useDailyState(true);
  const [error, setError] = useDailyState('');

  useDailyEffect(() => {
    let alive = true;
    setLoading(true);
    setError('');
    getDailyPanelLatest('postmarket')
      .then((data) => {
        if (!alive) return;
        setPanel(data);
      })
      .catch((err) => {
        if (!alive) return;
        setPanel(null);
        setError(err?.message || 'daily_panel 加载失败');
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => { alive = false; };
  }, []);

  const visibleCards = useDailyMemo(() => {
    const cards = panel?.cards || [];
    if (tab === 'all') return cards;
    if (tab === 'blocked') return cards.filter((card) => ['missing', 'blocked', 'degraded'].includes(card.status));
    return cards.filter((card) => card.lifecycle === tab);
  }, [panel, tab]);

  return (
    <div className="grid" style={{ gap: 14, minWidth: 0 }}>
      <PageHead
        eyebrow="Daily Workflow"
        title="日常"
        desc="查看当天变化与证据，记录自己的研究选择，并追踪后续观察。"
        right={<button type="button" className="btn btn-sm" onClick={() => navigate('/reports')}>复盘案卷</button>}
      />

      <section className="glass pop" style={{ padding: 14 }} aria-label="研究与观点入口">
        <div className="spread" style={{ gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
          <div>
            <div className="t-eyebrow">Human confirmation</div>
            <div className="t-dim" style={{ fontSize: 12.5, marginTop: 3 }}>
              在此核对证据并保存个人研究意见。接受或修改意见只留下记录，不执行交易或改动仓位。
            </div>
          </div>
          <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
            <button type="button" className="btn btn-primary" onClick={() => navigate('/chat')}>研究目标</button>
            <button type="button" className="btn" onClick={() => navigate('/chat')}>记录观点</button>
          </div>
        </div>
        <HumanReviewPanel asOf={panel?.as_of || null} />
      </section>

      <div className="row pop" role="tablist" aria-label="daily lifecycle tabs" style={{ gap: 6, flexWrap: 'wrap' }}>
        {TABS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={`navlink ${tab === id ? 'on' : ''}`}
            style={{ border: '1px solid var(--hairline-soft)' }}
            onClick={() => setTab(id)}
          >
            <span>{label}</span>
          </button>
        ))}
      </div>

      {loading && <EmptyState text="加载 daily_panel.v1..." />}
      {!loading && panel && (
        <>
          <DailyPanelHeader panel={panel} />
          <DailyPanelCards cards={visibleCards} />
        </>
      )}
      {!loading && !panel && (
        <>
          <EmptyState text={error || 'daily_panel 暂不可用，展示 legacy fallback。'} />
          <LegacyReportFallback active />
        </>
      )}
    </div>
  );
}

Object.assign(window, { DailyPage });
