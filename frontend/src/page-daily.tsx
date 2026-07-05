// ============================================================
// 日常 — M63 日常报告 / M59 裁量参考
// ============================================================
import React from 'react';
import { getLatestM59Discretion, getLatestM63Report, getM63Queue } from './api';
import { Badge, Markdown, McIcon, PageHead } from './shared';

const { useEffect: useDailyEffect, useState: useDailyState } = React;

const DAILY_TABS = [
  ['premarket', '盘前'],
  ['intraday', '盘中'],
  ['postmarket', '盘后'],
  ['weekly', '周末'],
];

function EmptyState({ text }: any) {
  return (
    <div className="glass" style={{ padding: 18, color: 'var(--ink-3)', fontSize: 13 }}>
      {text}
    </div>
  );
}

function QueuePanel({ queue, loading }: any) {
  const pending = queue?.pending || [];
  return (
    <aside className="glass pop" style={{ padding: 16, alignSelf: 'start' }}>
      <div className="card-head" style={{ padding: 0, border: 0 }}>
        <div>
          <div className="t-eyebrow">Research Queue</div>
          <h2 className="t-title" style={{ margin: '2px 0 0', fontSize: 16 }}>待研究队列</h2>
        </div>
        <Badge tone="badge-dim">{pending.length}</Badge>
      </div>
      <div className="grid" style={{ gap: 10, marginTop: 14 }}>
        {loading && <div className="t-faint" style={{ fontSize: 12 }}>加载中...</div>}
        {!loading && pending.length === 0 && <div className="t-faint" style={{ fontSize: 12 }}>暂无待处理条目</div>}
        {pending.map((item) => (
          <div key={item.id || `${item.target}-${item.trigger_rule}`} className="glass-inset" style={{ padding: '12px 13px' }}>
            <div className="spread" style={{ gap: 8, alignItems: 'center' }}>
              <strong className="t-num" style={{ fontSize: 14 }}>{item.target || '未标注'}</strong>
              <Badge tone="badge-accent">{item.trigger_rule || 'trigger'}</Badge>
            </div>
            {item.reason && <div className="t-dim" style={{ fontSize: 12.5, lineHeight: 1.55, marginTop: 8 }}>{item.reason}</div>}
          </div>
        ))}
      </div>
    </aside>
  );
}

function DiscretionCards({ items }: any) {
  if (!items?.length) return null;
  return (
    <section className="grid pop" style={{ gap: 10 }}>
      <div className="spread" style={{ alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div className="t-eyebrow">M59 Observe Only</div>
          <h2 className="t-title" style={{ margin: '2px 0 0' }}>🧭 裁量参考区</h2>
        </div>
        <Badge tone="badge-dim">{items[0]?.as_of || 'latest'}</Badge>
      </div>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 10 }}>
        {items.map((item) => {
          const card = item.card || {};
          const title = `${item.symbol || '未知'} · ${item.slot || 'card'}`;
          return (
            <article key={`${item.symbol}-${item.slot}-${item.created_at}`} className="glass" style={{ padding: 15 }}>
              <div className="spread" style={{ alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' }}>
                <div style={{ minWidth: 0 }}>
                  <div className="t-eyebrow">{item.provider || 'provider'}</div>
                  <h3 className="t-title" style={{ margin: '3px 0 0', fontSize: 15.5 }}>{title}</h3>
                </div>
                <span className="badge badge-warn" style={{ maxWidth: 210, whiteSpace: 'normal', lineHeight: 1.35 }}>
                  仅供研究参考,不构成投资建议
                </span>
              </div>
              <div className="grid" style={{ gap: 8, marginTop: 13 }}>
                <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
                  {card.stance && <Badge tone="badge-accent">{card.stance}</Badge>}
                  {card.confidence && <Badge tone="badge-dim">{card.confidence}</Badge>}
                </div>
                {card.timing_note && <div className="t-dim" style={{ fontSize: 12.5, lineHeight: 1.55 }}>{card.timing_note}</div>}
                {card.rationale && <div style={{ fontSize: 13, lineHeight: 1.6 }}>{card.rationale}</div>}
                {card.reevaluation_trigger && (
                  <div className="glass-inset" style={{ padding: '9px 10px', fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.5 }}>
                    {card.reevaluation_trigger}
                  </div>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function DailyPage() {
  const [tab, setTab] = useDailyState('premarket');
  const [report, setReport] = useDailyState<any>(null);
  const [queue, setQueue] = useDailyState<any>({ pending: [], done: [] });
  const [cards, setCards] = useDailyState<any[]>([]);
  const [loading, setLoading] = useDailyState(false);
  const [queueLoading, setQueueLoading] = useDailyState(false);
  const [error, setError] = useDailyState('');

  useDailyEffect(() => {
    let alive = true;
    setLoading(true);
    setError('');
    getLatestM63Report(tab)
      .then((data) => {
        if (!alive) return;
        setReport(data);
      })
      .catch((err) => {
        if (!alive) return;
        setReport(null);
        setError(err?.status === 404 ? '暂无该时段报告' : '报告加载失败');
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => { alive = false; };
  }, [tab]);

  useDailyEffect(() => {
    let alive = true;
    setQueueLoading(true);
    getM63Queue()
      .then((data) => { if (alive) setQueue(data || { pending: [], done: [] }); })
      .catch(() => { if (alive) setQueue({ pending: [], done: [] }); })
      .finally(() => { if (alive) setQueueLoading(false); });
    return () => { alive = false; };
  }, []);

  useDailyEffect(() => {
    let alive = true;
    if (tab !== 'postmarket') {
      setCards([]);
      return () => { alive = false; };
    }
    getLatestM59Discretion()
      .then((data) => { if (alive) setCards(Array.isArray(data) ? data : []); })
      .catch(() => { if (alive) setCards([]); });
    return () => { alive = false; };
  }, [tab]);

  return (
    <div className="grid" style={{ gap: 14 }}>
      <PageHead
        eyebrow="Daily Workflow"
        title="日常"
        desc="明仓按交易节奏分了六个工作流入口：盘前看、盘中记、盘后决、周末体检、研究 <目标>、喂观点。"
      />

      <div className="row pop" style={{ gap: 6, flexWrap: 'wrap' }}>
        {DAILY_TABS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={`navlink ${tab === id ? 'on' : ''}`}
            style={{ border: '1px solid var(--hairline-soft)' }}
            onClick={() => setTab(id)}
          >
            <McIcon name={id === 'weekly' ? 'schedule' : 'reports'} size={15} />
            <span>{label}</span>
          </button>
        ))}
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 320px), 1fr))', gap: 12 }}>
        <div className="grid" style={{ gap: 12, minWidth: 0 }}>
          <section className="glass pop" style={{ padding: 18, minWidth: 0 }}>
            <div className="spread" style={{ alignItems: 'center', gap: 12, marginBottom: 12 }}>
              <div>
                <div className="t-eyebrow">M63 Report</div>
                <h2 className="t-title" style={{ margin: '2px 0 0' }}>{report?.mode || tab}</h2>
              </div>
              {report?.as_of && <Badge tone="badge-dim">{report.as_of}</Badge>}
            </div>
            {loading && <EmptyState text="加载中..." />}
            {!loading && error && <EmptyState text={error} />}
            {!loading && !error && <Markdown text={report?.text || ''} />}
          </section>
          {tab === 'postmarket' && <DiscretionCards items={cards} />}
        </div>
        <QueuePanel queue={queue} loading={queueLoading} />
      </div>
    </div>
  );
}

Object.assign(window, { DailyPage });
