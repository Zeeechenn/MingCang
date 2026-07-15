import React from 'react';

import {
  createNewsShadowFeedback,
  getNewsShadowRun,
  getNewsShadowRuns,
  getNewsShadowSummary,
} from './services/news-shadow';
import { Badge, Card, Metric, PageHead, Toggle, fmt, toast } from './shared';

const { useEffect, useState } = React;

const STATUS_LABELS = {
  evidence: '已有证据',
  no_evidence: '库内无证据',
  verified_no_news: '已核验无新闻',
  fetch_failed: '抓取失败',
  score_failed: '打分失败',
};

const FEEDBACK_OPTIONS = [
  ['missing_evidence', '证据缺失'],
  ['stale_evidence', '证据过时'],
  ['duplicate_evidence', '证据重复'],
  ['wrong_entity_link', '股票关联错误'],
  ['wrong_event_class', '事件分类错误'],
  ['wrong_sentiment_direction', '情绪方向错误'],
  ['wrong_materiality', '重要性错误'],
  ['wrong_trigger_threshold', '触发阈值错误'],
  ['fusion_dilution', '融合稀释重大事件'],
  ['unusable_explanation', '解释不可用'],
  ['action_disagreement', '动作分歧需复核'],
  ['legacy_better', '旧链路更好'],
  ['pyramid_better', '金字塔更好'],
  ['other', '其他'],
];

const EVENT_LEVEL_LABELS = {
  high: '高',
  medium: '中',
  low: '低',
  unavailable: '不可用',
};

const REVIEW_BUCKET_LABELS = {
  action_divergence: '动作分歧',
  high_importance_untriggered: '高重要性未触发',
  stable_control: '稳定对照',
  routine: '常规样本',
};

const REASON_LABELS = {
  new_announcement_event: '新公告事件',
  price_change_anomaly: '价格异动',
  volume_anomaly: '成交量异动',
  price_volume_input_missing: '价量输入缺失',
  policy_keyword_hit: '政策/监管词命中',
  source_diversity_surge: '来源多样性突增',
  l0_event_score_threshold: '事件重要性过阈',
  high_importance_untriggered: '高重要性证据未触发',
  l1_not_triggered: 'L1 未触发',
  company_event: '公司事件',
  regulation_policy: '监管/政策',
  industry_peer: '行业/同业',
  market_sentiment: '市场情绪',
};

const COLLECTION_LABELS = {
  success: '采集成功',
  failed: '采集失败',
  not_run: '本轮未采集',
};

const CONTENT_LABELS = {
  full: '正文',
  excerpt: '摘要',
  title_only: '仅标题',
};

function reasonLabel(reason) {
  if (reason.startsWith('main_cause:')) return `主因：${REASON_LABELS[reason.slice(11)] || reason.slice(11)}`;
  if (reason.startsWith('l0_materiality:')) return `L0 重要性 ${reason.slice(15)}`;
  return REASON_LABELS[reason] || reason;
}

function statusTone(status) {
  if (status === 'evidence') return 'badge-accent';
  if (status === 'verified_no_news') return 'badge-dim';
  return 'badge-warn';
}

function score(value) {
  return value === null || value === undefined ? '–' : fmt.signed(value, 1);
}

function RunList({ runs, selectedId, onSelect }) {
  if (!runs.length) return <div className="empty">当前筛选下没有生产镜像记录。先跑一次 M68 盘后镜像，或清空筛选条件。</div>;
  return (
    <div className="grid" style={{ gap: 8 }}>
      {runs.map((run) => (
        <button
          key={run.run_id}
          type="button"
          className="glass-inset"
          aria-pressed={selectedId === run.run_id}
          onClick={() => onSelect(run.run_id)}
          style={{
            padding: '11px 13px',
            borderColor: selectedId === run.run_id ? 'var(--accent)' : undefined,
            cursor: 'pointer',
            color: 'inherit',
            textAlign: 'left',
          }}
        >
          <div className="spread" style={{ gap: 8 }}>
            <div className="row" style={{ gap: 7, minWidth: 0 }}>
              <strong className="t-num" style={{ fontSize: 13 }}>{run.symbol}</strong>
              <Badge tone={statusTone(run.status)}>{STATUS_LABELS[run.status] || run.status}</Badge>
              {run.review_bucket && run.review_bucket !== 'routine' && <Badge tone="badge-dim">{REVIEW_BUCKET_LABELS[run.review_bucket] || run.review_bucket}</Badge>}
            </div>
            <span className="t-num t-faint" style={{ fontSize: 11 }}>{run.as_of}</span>
          </div>
          <div className="spread" style={{ gap: 8, marginTop: 8, fontSize: 12 }}>
            <span className="t-dim">旧 {score(run.legacy.composite_score)} → 影子 {score(run.counterfactual.composite_score)}</span>
            {run.counterfactual.would_change_action && <Badge tone="badge-warn">动作分歧</Badge>}
          </div>
          <div className="t-faint" style={{ fontSize: 11, marginTop: 5 }}>
            证据 {run.evidence.count ?? 0} · 正文覆盖 {run.evidence.content_coverage === null || run.evidence.content_coverage === undefined ? '–' : `${Math.round(run.evidence.content_coverage * 100)}%`}
          </div>
        </button>
      ))}
    </div>
  );
}

function EvidenceManifest({ evidence }) {
  const items = evidence?.items || [];
  if (!items.length) return <div className="empty">没有可展示的证据清单。请先判断是“库内无证据”、抓取失败，还是确实无新闻。</div>;
  return (
    <div className="grid" style={{ gap: 8 }}>
      {items.map((item, index) => (
        <div className="glass-inset" key={`${item.url}-${index}`} style={{ padding: '10px 12px' }}>
          <div className="spread" style={{ alignItems: 'flex-start', gap: 10 }}>
            <div style={{ minWidth: 0 }}>
              {/^https?:\/\//.test(item.url || '') ? (
                <a className="link" href={item.url} target="_blank" rel="noreferrer" style={{ fontSize: 12.5, lineHeight: 1.45 }}>{item.title}</a>
              ) : (
                <div style={{ fontSize: 12.5, lineHeight: 1.45 }}>{item.title}</div>
              )}
              <div className="t-faint" style={{ fontSize: 11, marginTop: 4 }}>{item.source} · {item.provider} · {item.published_at}</div>
            </div>
            <Badge tone={item.content_status === 'title_only' ? 'badge-warn' : 'badge-dim'}>{CONTENT_LABELS[item.content_status] || item.content_status}</Badge>
          </div>
        </div>
      ))}
    </div>
  );
}

function RunDetail({ detail, onFeedbackSaved }) {
  const [category, setCategory] = useState('missing_evidence');
  const [preferredPath, setPreferredPath] = useState('unclear');
  const [evidenceRef, setEvidenceRef] = useState('');
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => { setEvidenceRef(''); }, [detail?.run_id]);

  if (!detail) return <div className="empty">从左侧选择一条记录，查看证据、触发原因、归因和旧/新链路分歧。</div>;

  async function saveFeedback(event) {
    event.preventDefault();
    setSaving(true);
    try {
      await createNewsShadowFeedback(detail.run_id, {
        category,
        preferred_path: preferredPath,
        evidence_ref: evidenceRef || null,
        note: note.trim() || null,
      });
      setNote('');
      toast('问题已记入 M68 反馈账本');
      await onFeedbackSaved();
    } catch (error) {
      toast(`反馈保存失败：${error instanceof Error ? error.message : '未知错误'}`);
    } finally {
      setSaving(false);
    }
  }

  const reasons = detail.pyramid.trigger_reasons || [];
  const eventReasons = detail.event_risk?.reasons || [];
  const attribution = detail.pyramid.attribution;
  const pv = detail.evidence?.price_volume || {};
  return (
    <div className="grid" style={{ gap: 14 }}>
      <Card
        eyebrow={`${detail.symbol} · ${detail.as_of}`}
        title="旧链路与金字塔影子对照"
        right={<Badge tone={statusTone(detail.status)}>{STATUS_LABELS[detail.status] || detail.status}</Badge>}
      >
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(135px, 1fr))', gap: 8 }}>
          <Metric label="旧综合分" value={score(detail.legacy.composite_score)} sub={`${detail.legacy.recommendation || '无官方信号'} · ${detail.legacy.signal_date || '无日期'}`} />
          <Metric label="金字塔情绪" value={score(detail.pyramid.sentiment_score)} sub={`置信 ${detail.pyramid.confidence === null ? '–' : fmt.price(detail.pyramid.confidence, 2)}`} />
          <Metric label="事件关注" value={EVENT_LEVEL_LABELS[detail.event_risk.level] || detail.event_risk.level} sub="复核优先级，不代表涨跌" />
          <Metric label="只替换情绪腿" value={score(detail.counterfactual.composite_score)} sub={detail.counterfactual.recommendation || '不可计算'} />
          <Metric label="综合分变化" value={score(detail.counterfactual.score_delta)} sub={detail.counterfactual.would_change_action ? '动作分歧，必须复核' : '未改变动作'} />
        </div>
        <div className="glass-inset" style={{ padding: '11px 13px', marginTop: 10, fontSize: 12.5, lineHeight: 1.55 }}>
          <strong>解释边界：</strong>{detail.counterfactual.note || detail.legacy.summary}
        </div>
        {detail.error && <div className="empty" role="alert" style={{ marginTop: 10 }}><b>本次链路错误：</b>{detail.error}</div>}
      </Card>

      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: 10 }}>
        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">L1 触发原因</div>
          <div className="row" style={{ gap: 5, flexWrap: 'wrap', marginTop: 8 }}>
            {reasons.length ? reasons.map((reason) => <Badge key={reason} tone="badge-dim">{reasonLabel(reason)}</Badge>) : <span className="t-faint" style={{ fontSize: 12 }}>没有触发原因</span>}
          </div>
          {!!eventReasons.length && <div className="t-faint" style={{ fontSize: 11.5, marginTop: 8 }}>风险复核：{eventReasons.map(reasonLabel).join(' · ')}</div>}
        </div>
        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">价格量能输入</div>
          <div className="grid" style={{ gap: 5, marginTop: 8, fontSize: 12.5 }}>
            <div className="spread"><span className="t-faint">单日涨跌</span><span className="t-num">{fmt.signedPct(detail.price_volume.price_change_pct)}</span></div>
            <div className="spread"><span className="t-faint">20日量比</span><span className="t-num">{fmt.price(detail.price_volume.volume_ratio, 2)}</span></div>
            <div className="spread"><span className="t-faint">可用日线</span><span className="t-num">{pv.price_bars_available ?? '–'}</span></div>
          </div>
        </div>
        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">异动归因</div>
          {attribution ? (
            <div className="grid" style={{ gap: 5, marginTop: 8, fontSize: 12.5 }}>
              <div className="spread"><span className="t-faint">主因</span><Badge tone="badge-accent">{REASON_LABELS[attribution.main_cause] || attribution.main_cause}</Badge></div>
              <div className="spread"><span className="t-faint">重检逻辑</span><span>{attribution.thesis_recheck ? '需要' : '不需要'}</span></div>
              <div className="spread"><span className="t-faint">时间线</span><span className="t-num">{attribution.timeline?.length || 0}</span></div>
            </div>
          ) : <div className="t-faint" style={{ fontSize: 12, marginTop: 8 }}>未触发归因卡</div>}
        </div>
        <div className="glass-inset" style={{ padding: 13 }}>
          <div className="t-eyebrow">证据采集状态</div>
          <div className="grid" style={{ gap: 5, marginTop: 8, fontSize: 12.5 }}>
            <div className="spread"><span className="t-faint">采集结果</span><span>{COLLECTION_LABELS[detail.evidence?.collection_outcome] || detail.evidence?.collection_outcome || '未知'}</span></div>
            <div className="spread"><span className="t-faint">正文覆盖</span><span className="t-num">{detail.evidence?.content_coverage === null || detail.evidence?.content_coverage === undefined ? '–' : `${Math.round(detail.evidence.content_coverage * 100)}%`}</span></div>
            <div className="spread"><span className="t-faint">来源数</span><span className="t-num">{detail.evidence?.source_diversity ?? '–'}</span></div>
          </div>
        </div>
      </div>

      <Card eyebrow="Evidence" title={`证据清单 · ${detail.evidence?.count || 0} 条`}>
        <EvidenceManifest evidence={detail.evidence} />
      </Card>

      <Card eyebrow="Trial Feedback" title="标记问题，形成可复现样本">
        <form onSubmit={saveFeedback} className="grid" style={{ gap: 9 }}>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 8 }}>
            <select className="field" aria-label="问题类型" value={category} onChange={(event) => setCategory(event.target.value)}>
              {FEEDBACK_OPTIONS.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
            </select>
            <select className="field" aria-label="关联证据" value={evidenceRef} onChange={(event) => setEvidenceRef(event.target.value)}>
              <option value="">整条运行（不指定证据）</option>
              {(detail.evidence?.items || []).map((item) => <option value={item.evidence_id} key={item.evidence_id}>{item.title}</option>)}
            </select>
            <select className="field" aria-label="更可信链路" value={preferredPath} onChange={(event) => setPreferredPath(event.target.value)}>
              <option value="unclear">暂不确定哪条更好</option>
              <option value="legacy">旧链路更可信</option>
              <option value="pyramid">金字塔更可信</option>
            </select>
          </div>
          <textarea className="field" aria-label="反馈说明" value={note} onChange={(event) => setNote(event.target.value)} placeholder="写清缺了什么证据、哪条归因不对、为什么动作分歧不合理…" style={{ minHeight: 74, resize: 'vertical' }} />
          <div className="spread" style={{ gap: 8, flexWrap: 'wrap' }}>
            <span className="t-faint" style={{ fontSize: 11.5 }}>已记录 {detail.feedback?.length || 0} 条反馈；不会反写模型或生产信号。</span>
            <button className="btn btn-sm btn-primary" type="submit" disabled={saving}>{saving ? '保存中…' : '保存问题样本'}</button>
          </div>
        </form>
      </Card>
    </div>
  );
}

export function NewsShadowPage() {
  const [summary, setSummary] = useState<any>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [detail, setDetail] = useState<any>(null);
  const [selectedId, setSelectedId] = useState('');
  const [asOf, setAsOf] = useState('');
  const [symbol, setSymbol] = useState('');
  const [onlyDivergent, setOnlyDivergent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  async function load(options: { keepId?: string } = {}) {
    setLoading(true);
    setError('');
    try {
      const [nextSummary, nextRuns] = await Promise.all([
        getNewsShadowSummary(asOf),
        getNewsShadowRuns({ asOf, symbol: symbol.trim(), onlyDivergent, limit: 200 }),
      ]);
      setSummary(nextSummary);
      setRuns(nextRuns);
      const keepId = options.keepId || selectedId;
      const nextId = nextRuns.some((item) => item.run_id === keepId) ? keepId : (nextRuns[0]?.run_id || '');
      setSelectedId(nextId);
      setDetail(nextId ? await getNewsShadowRun(nextId) : null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '加载失败');
      setRuns([]);
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }

  async function selectRun(runId) {
    setSelectedId(runId);
    try {
      setDetail(await getNewsShadowRun(runId));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '详情加载失败');
    }
  }

  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps -- filters apply only on button click

  return (
    <div className="grid" style={{ gap: 14 }}>
      <PageHead
        eyebrow="M68 · Production Mirror · Observe Only"
        title="新闻金字塔试用台"
        desc="用真实生产库证据并排看旧链路与金字塔；重点发现证据缺失、误触发、错归因和动作分歧。这里没有生产决策权。"
        right={<Badge tone="badge-warn">方向预测仍未过门槛</Badge>}
      />

      <div className="glass-inset" style={{ padding: '12px 15px', lineHeight: 1.6, fontSize: 13 }}>
        <strong>当前判断：</strong>A 股情绪更适合解释波动幅度和事件风险；尚无证据支持单靠情绪稳定预测方向。因此先试用“事件/风险槽位”，方向只做影子对照。
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
        <Metric label="镜像记录" value={summary?.total ?? '–'} sub={`有证据 ${summary?.with_evidence ?? '–'}`} />
        <Metric label="动作分歧" value={summary?.would_change_action ?? '–'} sub="优先人工复核" />
        <Metric label="价量完整" value={summary?.price_volume_complete ?? '–'} sub="涨跌 + 20 日量比" />
        <Metric label="高事件关注" value={summary?.event_risk?.high ?? 0} sub="只表示优先复核" />
        <Metric label="三桶复核" value={(summary?.review_queue?.action_divergence?.length || 0) + (summary?.review_queue?.high_importance_untriggered?.length || 0) + (summary?.review_queue?.stable_control?.length || 0)} sub={`分歧 ${summary?.review_queue?.action_divergence?.length || 0} · 漏触发 ${summary?.review_queue?.high_importance_untriggered?.length || 0} · 对照 ${summary?.review_queue?.stable_control?.length || 0}`} />
        <Metric label="平均分差" value={summary?.mean_absolute_score_delta ?? '–'} sub="绝对综合分变化" />
        <Metric label="已知 token" value={summary?.tokens_spent_known ?? '–'} sub={`未知 ${summary?.tokens_unknown_runs ?? '–'} 条`} />
      </div>

      <Card eyebrow="Filters" title="定位问题样本">
        <div className="grid" style={{ gridTemplateColumns: '150px minmax(150px, 1fr) auto auto', gap: 8, alignItems: 'center' }} data-grid="news-shadow-filters">
          <input className="field" type="date" aria-label="镜像日期" value={asOf} onChange={(event) => setAsOf(event.target.value)} />
          <input className="field" aria-label="股票代码" value={symbol} onChange={(event) => setSymbol(event.target.value)} placeholder="股票代码，留空看全部" />
          <div className="row" style={{ gap: 7 }}><Toggle on={onlyDivergent} onChange={setOnlyDivergent} label="只看动作分歧" /><span style={{ fontSize: 12 }}>只看动作分歧</span></div>
          <button className="btn btn-sm" type="button" disabled={loading} onClick={() => void load()}>{loading ? '加载中…' : '应用筛选'}</button>
        </div>
      </Card>

      {error && <div className="empty" role="alert"><b>镜像数据加载失败。</b> {error}</div>}

      <div className="news-shadow-layout">
        <Card eyebrow="Runs" title={`镜像记录 · ${runs.length}`} className="pop">
          <RunList runs={runs} selectedId={selectedId} onSelect={selectRun} />
        </Card>
        <RunDetail detail={detail} onFeedbackSaved={() => load({ keepId: selectedId })} />
      </div>
    </div>
  );
}

window.NewsShadowPage = NewsShadowPage;
