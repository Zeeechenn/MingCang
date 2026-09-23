import React, { useEffect, useRef, useState } from 'react';
import { Card } from '../../shared';
import { chatWithAIStream } from '../../services/api';
import { loadResearchContext, loadResearchMessages, loadResearchReviews, saveResearchObservation, saveResearchReview } from '../../services/research-context';
import type { ResearchContext, ResearchSelection, ResearchSource } from '../../services/research-context';

const labels: Record<string, string> = { revenue_yoy: '营收同比', net_profit_yoy: '净利同比', total_assets: '总资产', total_equity: '股东权益', long_term_debt: '长期负债', asset_turnover: '资产周转率', open: '开盘', high: '最高', low: '最低', close: '收盘', volume: '成交量（单位待核）', atr14: 'ATR14', revenue: '营收', net_profit: '净利润', operating_cf: '经营现金流', roe: 'ROE', gross_margin: '毛利率', current_ratio: '流动比率' };
const outcomeLabels = { supported: '观察支持原判断', contradicted: '观察反驳原判断', inconclusive: '证据仍不足', not_observed: '尚未观察到' };
function priorDay(day: string, days: number) { const d = new Date(`${day}T00:00:00Z`); d.setUTCDate(d.getUTCDate() - days); return d.toISOString().slice(0, 10); }
function failure(error: any) {
  if (/page_evidence_changed/.test(String(error?.message))) return '证据已更新，请重新载入后再提交。';
  if (/page_evidence_incomplete/.test(String(error?.message))) return '资料存在缺口，暂不能向 AI 提问。';
  return error?.message || '请求未完成，请稍后重试。';
}

function Sources({ rows, prefix }: { rows: ResearchSource[]; prefix: string }) {
  return <div style={{ display: 'grid', gap: 6 }}>
    {rows.map(row => <details key={row.id} id={`${prefix}-${row.id}`} className="glass-inset" style={{ padding: 10, overflowWrap: 'anywhere' }}>
      <summary style={{ cursor: 'pointer', fontSize: 12 }}>{row.kind === 'price' ? '行情' : '财报'} · {row.date} · {row.source || '来源未知'}</summary>
      <p className="t-faint" style={{ fontSize: 12 }}>{row.id} · {row.currency || '币种未知'} · {row.adjustment || '财务原值'}{row.disclosure_date ? ` · 披露 ${row.disclosure_date}` : ''}</p>
      <dl style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 8, margin: 0 }}>
        {Object.entries(row.values).map(([key, value]) => <div key={key}><dt className="t-dim" style={{ fontSize: 11 }}>{labels[key] || key}</dt><dd style={{ margin: 0, fontSize: 13 }}>{value == null ? '未知' : String(value)}</dd></div>)}
      </dl>
    </details>)}
  </div>;
}

function Observation({ review, onSaved }: { review: any; onSaved: (row: any) => void }) {
  const [status, setStatus] = useState('inconclusive'); const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const attempt = useRef<string | null>(null);
  async function save() {
    setBusy(true); setError(''); attempt.current ||= crypto.randomUUID();
    try {
      onSaved(await saveResearchObservation(review.review_id, { expected_version: review.result.version,
        observation_id: attempt.current, status, note })); setNote(''); attempt.current = null;
    } catch (e) { setError(failure(e)); } finally { setBusy(false); }
  }
  return <div style={{ display: 'grid', gap: 8, marginTop: 10 }}>
    {(review.result.outcomes || []).map((o: any) => <div key={o.observation_id} className="glass-inset" style={{ padding: 10 }}>
      <b>{outcomeLabels[o.status]}</b><p style={{ margin: '5px 0' }}>{o.note}</p><small className="t-faint">{o.recorded_at} · 人工观察，未经独立核验</small>
    </div>)}
    <label>后续观察<select aria-label="后续观察" value={status} onChange={e => { setStatus(e.target.value); attempt.current = null; }} disabled={busy} className="input" style={{ width: '100%' }}>
      {Object.entries(outcomeLabels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
    </select></label>
    <textarea aria-label="观察依据" className="input" placeholder="记录新公告、数据日期及支持或反驳的理由" value={note} maxLength={4000} disabled={busy} onChange={e => { setNote(e.target.value); attempt.current = null; }} />
    <button className="btn btn-sm" disabled={busy || !note.trim()} onClick={save}>{busy ? '保存中…' : '追加观察'}</button>
    {error && <div role="alert">{error}</div>}
  </div>;
}

export function EvidenceWorkspace({ symbol, endDate, enabled }: { symbol: string; endDate?: string; enabled: boolean }) {
  const day = endDate || priorDay(new Date().toISOString().slice(0, 10), 1);
  const [start, setStart] = useState(priorDay(day, 90)); const [end, setEnd] = useState(day);
  const [context, setContext] = useState<ResearchContext | null>(null); const [reload, setReload] = useState(0);
  const [restoring, setRestoring] = useState(false);
  const [restoreFailed, setRestoreFailed] = useState(false); const [historyReload, setHistoryReload] = useState(0);
  const [loading, setLoading] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const [question, setQuestion] = useState(''); const [answers, setAnswers] = useState<any[]>([]); const [reviews, setReviews] = useState<any[]>([]);
  const [judgment, setJudgment] = useState(''); const [rationale, setRationale] = useState(''); const [watchFor, setWatchFor] = useState('');
  const generation = useRef(0); const session = useRef<string | null>(null);
  const selection: ResearchSelection = { symbol, market: 'CN', start, as_of: end, adjustment: 'stored' };
  const current = context && Object.entries(selection).every(([k, v]) => context.selection[k] === v) ? context : null;
  useEffect(() => {
    const seq = ++generation.current; let active = true;
    if (!enabled) return;
    setLoading(true); setError(''); setContext(null);
    loadResearchContext({ symbol, market: 'CN', start, as_of: end, adjustment: 'stored' }).then(value => {
      if (active && seq === generation.current) setContext(value);
    }).catch(e => { if (active) setError(failure(e)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [symbol, start, end, reload, enabled]);
  useEffect(() => {
    let active = true; session.current = null; setReviews([]); setAnswers([]);
    if (!enabled) return;
    setRestoring(true); setRestoreFailed(false);
    const restoreFailure = () => { if (active) setRestoreFailed(true); };
    const reviewsReady = loadResearchReviews(symbol).then(v => { if (active) setReviews(v.reviews); }).catch(restoreFailure);
    const id = localStorage.getItem(`mc_research_session_${symbol}`);
    const messagesReady = id ? loadResearchMessages(id).then(messages => {
      if (!active) return;
      const snapshots = new Map<string, ResearchContext>();
      messages.forEach(m => { if (m.context_snapshot) snapshots.set(m.context_snapshot.context_sha256, m.context_snapshot); });
      setAnswers(messages.filter(m => m.role === 'assistant' && m.research_claims?.length && m.research_context?.symbol === symbol)
        .map(m => ({ ...m, snapshot: snapshots.get(m.research_context.context_sha256) })));
      session.current = id;
    }).catch(restoreFailure) : Promise.resolve();
    Promise.all([reviewsReady, messagesReady]).finally(() => { if (active) setRestoring(false); });
    return () => { active = false; };
  }, [symbol, enabled, historyReload]);
  async function ask() {
    if (!current) return;
    const snapshot = current; const asked = question; setBusy(true); setError('');
    try {
      const result: any = await chatWithAIStream({ message: asked, mode: 'general', session_id: session.current,
        research_context: { ...snapshot.selection, context_sha256: snapshot.context_sha256 } }, {
        onError: data => { throw new Error(data.message); },
      });
      if (!result?.research_context || result.research_context.context_sha256 !== snapshot.context_sha256) throw new Error('回答未绑定所选证据。');
      session.current = result.session_id;
      if (result.session_id) localStorage.setItem(`mc_research_session_${symbol}`, result.session_id);
      setAnswers(old => [...old, { ...result, question: asked, snapshot }]); setQuestion('');
    } catch (e) { setError(failure(e)); } finally { setBusy(false); }
  }
  async function record() {
    if (!current) return; setBusy(true); setError('');
    try {
      const saved: any = await saveResearchReview({ context: { ...current.selection, context_sha256: current.context_sha256 }, judgment, rationale, watch_for: watchFor });
      setReviews(old => [saved, ...old.filter(r => r.review_id !== saved.review_id)]);
      setJudgment(''); setRationale(''); setWatchFor('');
    } catch (e) { setError(failure(e)); } finally { setBusy(false); }
  }
  const alreadySaved = reviews.some(r => r.source.context_sha256 === current?.context_sha256);
  return <Card title="基于本页证据研究" eyebrow="资料 → 提问 → 判断 → 后续观察">
    {!enabled ? <p className="t-dim">连接真实后端后，可载入同一版本的资料、提问并保存判断。演示数据不提交研究记录。</p> : <div style={{ display: 'grid', gap: 12 }}>
      <p className="t-dim" style={{ margin: 0 }}>以下研究区单独绑定股票和日期。页面其他卡片仍展示其原始日期；AI 只读取本区的行情与财务资料。</p>
      <div className="row" style={{ flexWrap: 'wrap', gap: 10 }}>
        <label>起始日<input className="input" aria-label="证据起始日" type="date" value={start} onChange={e => setStart(e.target.value)} disabled={busy} /></label>
        <label>截止日<input className="input" aria-label="证据截止日" type="date" value={end} onChange={e => setEnd(e.target.value)} disabled={busy} /></label>
        <button className="btn btn-sm" onClick={() => setReload(v => v + 1)} disabled={busy || loading}>重新载入证据</button>
      </div>
      {loading && <p role="status">载入所选证据…</p>}
      {error && <div role="alert" className="glass-inset" style={{ padding: 10 }}>{error}</div>}
      {restoreFailed && <div role="alert">历史记录未能完整读取，请重新载入后再提交。
        <button className="btn btn-sm" onClick={() => setHistoryReload(v => v + 1)} disabled={restoring}>重新载入历史记录</button>
      </div>}
      {current && <>
        <div className="glass-inset" style={{ padding: 12 }}><b>{symbol} · {start} 至 {end}</b>
          <p className="t-faint" style={{ margin: '5px 0' }}>存储原口径 · {current.sources.length} 条源记录 · 版本 {current.context_sha256.slice(0, 10)}</p>
          {current.gaps.map(g => <p key={g} className="warn">{g}</p>)}
          <details><summary>资料限制</summary><ul>{current.limitations.map(v => <li key={v}>{v}</li>)}</ul></details>
        </div>
        <details><summary>查看本页原始证据</summary><Sources rows={current.sources} prefix="current-evidence" /></details>
        <label>向 AI 提问<textarea aria-label="本页研究问题" className="input" style={{ width: '100%', minHeight: 75 }} value={question} maxLength={2000} onChange={e => setQuestion(e.target.value)} placeholder="例如：当前现金流能否支持利润增长？还缺哪些资料？" /></label>
        <button className="btn btn-primary" disabled={busy || restoring || restoreFailed || !current.can_ask || !question.trim()} onClick={ask}>{busy ? '处理中…' : '基于这些证据提问'}</button>
        {!current.can_ask && <p className="t-dim">先补齐上方资料缺口，再调用 AI。可以记录待核实判断。</p>}
      </>}
      {answers.map((a, index) => <article className="glass-inset" key={index} style={{ padding: 12, overflowWrap: 'anywhere' }}>
        <b>研究回答 · {a.research_context.symbol} · {a.research_context.as_of}</b>
        <p className="t-faint">{a.research_context.context_sha256 === current?.context_sha256 ? '与当前证据一致' : '原股票 / 日期 / 资料版本的回答，不适用于当前选择'} · 模型判断待人工核实</p>
        {a.question && <p>{a.question}</p>}
        {a.research_claims.map((c: any, n: number) => <div key={n}><p style={{ whiteSpace: 'pre-wrap' }}>{c.text}</p>
          <small>依据：{c.evidence_ids.join('、')}</small>
          {a.snapshot && <details><summary>查看这条判断引用的证据</summary><Sources rows={a.snapshot.sources.filter(s => c.evidence_ids.includes(s.id))} prefix={`answer-${index}-${n}`} /></details>}
        </div>)}
      </article>)}
      {current && <fieldset disabled={busy || restoring || restoreFailed || alreadySaved} style={{ border: '1px solid var(--hairline-soft)', borderRadius: 12, padding: 12, minWidth: 0 }}>
        <legend>记录我的判断</legend>
        <div style={{ display: 'grid', gap: 8 }}>
          <input className="input" aria-label="我的判断" value={judgment} maxLength={2000} onChange={e => setJudgment(e.target.value)} placeholder="例如：继续观察，等待现金流改善" />
          <textarea className="input" aria-label="判断依据" value={rationale} maxLength={2000} onChange={e => setRationale(e.target.value)} placeholder="支持判断的证据和仍不确定的部分" />
          <textarea className="input" aria-label="后续验证条件" value={watchFor} maxLength={2000} onChange={e => setWatchFor(e.target.value)} placeholder="以后看到什么，会支持或推翻这条判断？" />
          <button className="btn btn-sm" onClick={record} disabled={!judgment.trim() || !rationale.trim() || !watchFor.trim() || !current.sources.length}>{alreadySaved ? '该证据版本已保存判断' : '保存判断与证据'}</button>
        </div>
      </fieldset>}
      <small className="t-faint">保存判断与追加观察不会下单、修改仓位或更新策略记忆；观察不等于已核实收益。</small>
      {reviews.map(review => <details className="glass-inset" style={{ padding: 12 }} key={review.review_id}>
        <summary>{review.source.selection.as_of} · {review.result.decision.judgment}</summary>
        <p>当时依据：{review.result.decision.rationale}</p><p>验证条件：{review.result.decision.watch_for}</p>
        <details><summary>查看当时保存的证据</summary><Sources rows={review.source.sources} prefix={review.review_id} /></details>
        <Observation review={review} onSaved={row => setReviews(old => old.map(r => r.review_id === row.review_id ? row : r))} />
      </details>)}
    </div>}
  </Card>;
}
