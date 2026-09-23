import { useEffect, useRef, useState } from 'react';
import {
  getDailyReviews, saveDailyReview, saveDailyReviewOutcome,
  type DailyReviews, type HumanReview, type HumanReviewSource, type ReviewChoice, type ReviewOutcome,
} from '../../services/daily';

const CHOICES: Record<ReviewChoice, string> = { accepted: '接受', modified: '修改', rejected: '拒绝' };
const OUTCOMES: Record<ReviewOutcome, string> = {
  supported: '观察支持我的判断', contradicted: '观察不支持我的判断', inconclusive: '仍无法核实', not_observed: '尚未观察',
};
const KINDS: Record<string, string> = { candidate: '候选研究', position_health: '持仓研究', human_confirmation: '研究待办' };
const ERRORS: Record<string, string> = {
  panel_changed_reload_required: '证据已变化，请刷新后重新核对。',
  source_expired_or_unverified: '证据已过期或未通过核对，请更新资料；仍可记录拒绝理由。',
  review_already_recorded_with_different_choice: '这条意见已记录过不同选择，请刷新查看；可追加后续观察。',
  review_version_conflict_reload_required: '记录已被另一窗口更新，请刷新后再补充。',
  panel_run_not_unique_or_complete: '暂无唯一完整批次，暂不提供新的人工复核。',
  committed_panel_missing: '缺少已提交面板，暂不提供新的人工复核。',
};
function errorText(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  return Object.entries(ERRORS).find(([key]) => message.includes(key))?.[1]
    || '未能确认保存结果，请先刷新核对记录。你的输入仍保留。';
}
function Original({ source }: { source: HumanReviewSource }) {
  return <details>
    <summary style={{ cursor: 'pointer' }}>查看原始证据</summary>
    <div className="t-faint" style={{ margin: '8px 0', overflowWrap: 'anywhere' }}>运行 {source.run_id} · 证据 {source.panel_sha256.slice(0, 12)}</div>
    <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: 12, maxHeight: 320, overflow: 'auto' }}>{JSON.stringify(source.original, null, 2)}</pre>
  </details>;
}
function Recorded({ review, onOutcome, busy }: { review: HumanReview; onOutcome: (value: HumanReview) => void; busy: boolean }) {
  const { decision, outcomes } = review.result;
  return <div className="grid" style={{ gap: 6 }}>
    <strong>已{CHOICES[decision.choice]}</strong>
    <div>我的理由：{decision.rationale}</div>
    {decision.revised_text && <div>修改后的判断：{decision.revised_text}</div>}
    <div className="t-faint">记录于 {review.result.recorded_at} · 尚未关联实际交易</div>
    {outcomes.length > 0 && <ul style={{ margin: 0, paddingLeft: 20 }}>{outcomes.map(item =>
      <li key={item.observation_id}>{OUTCOMES[item.status]}：{item.note} <span className="t-faint">（{item.recorded_at}，人工记录）</span></li>)}</ul>}
    <button type="button" className="btn btn-sm" disabled={busy} style={{ justifySelf: 'start' }} onClick={() => onOutcome(review)}>记录后续观察</button>
  </div>;
}

export function HumanReviewPanel({ asOf }: { asOf: string | null }) {
  const [data, setData] = useState<DailyReviews | null>(null);
  const [loadError, setLoadError] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('all');
  const [period, setPeriod] = useState('current');
  const [count, setCount] = useState(6);
  const [refresh, setRefresh] = useState(0);
  const [editing, setEditing] = useState<{ item: HumanReviewSource; choice: ReviewChoice } | null>(null);
  const [rationale, setRationale] = useState('');
  const [revision, setRevision] = useState('');
  const [outcome, setOutcome] = useState<{ review: HumanReview; id: string } | null>(null);
  const [outcomeStatus, setOutcomeStatus] = useState<ReviewOutcome>('inconclusive');
  const [outcomeNote, setOutcomeNote] = useState('');
  const outcomeForm = useRef<HTMLFormElement>(null);
  useEffect(() => { outcomeForm.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }); }, [outcome?.id]);

  useEffect(() => {
    if (!asOf) return;
    let alive = true;
    setLoading(true);
    setLoadError('');
    getDailyReviews(asOf).then(value => {
      if (!Array.isArray(value.items) || !Array.isArray(value.history)) throw new Error('invalid review response');
      if (alive) {
        setData(value);
        setOutcome(current => {
          if (!current) return null;
          const latest = value.history.find(review => review.review_id === current.review.review_id)
            || value.items.find(item => item.review?.review_id === current.review.review_id)?.review;
          return latest ? { ...current, review: latest } : current;
        });
      }
    })
      .catch(() => { if (alive) setLoadError('人工复核记录暂不可用，请刷新重试。'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [asOf, refresh]);

  function acceptResponse(review: HumanReview) {
    setData(current => current ? { ...current,
      items: current.items.map(item => item.item_id === review.source.item_id ? { ...item, review } : item),
      summary: current.summary ? { ...current.summary,
        recorded_choices: current.items.filter(item => item.review || item.item_id === review.source.item_id).length,
        with_observations: current.items.filter(item => (item.item_id === review.source.item_id ? review : item.review)?.result.outcomes.length).length,
      } : undefined,
      history: [review, ...current.history.filter(item => item.review_id !== review.review_id)].slice(0, current.history_limit),
    } : current);
  }
  function openChoice(item: HumanReviewSource, choice: ReviewChoice) {
    setEditing({ item, choice }); setRationale(''); setRevision(''); setError(''); setOutcome(null);
  }
  function openOutcome(review: HumanReview) {
    setOutcome({ review, id: crypto.randomUUID() }); setOutcomeNote(''); setError(''); setEditing(null);
  }
  async function submitChoice() {
    if (!editing || busy || !rationale.trim() || (editing.choice === 'modified' && !revision.trim())) return;
    setBusy(true); setError('');
    try {
      const saved = await saveDailyReview({ as_of: editing.item.panel_as_of, panel_sha256: editing.item.panel_sha256,
        item_id: editing.item.item_id, choice: editing.choice, rationale, revised_text: editing.choice === 'modified' ? revision : '' });
      acceptResponse(saved); setEditing(null);
    } catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  }
  async function submitOutcome() {
    if (!outcome || busy || !outcomeNote.trim()) return;
    setBusy(true); setError('');
    try {
      const saved = await saveDailyReviewOutcome(outcome.review.review_id, {
        expected_version: outcome.review.result.version, observation_id: outcome.id, status: outcomeStatus, note: outcomeNote,
      });
      acceptResponse(saved); setOutcome(null);
    } catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  }
  if (!asOf) return null;
  const filtered = (data?.items || []).filter(item => (period === 'all' || (item.source_scope || 'current') === period)
    && (kind === 'all' || item.card_type === kind)
    && `${item.name} ${item.subject} ${item.summary}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="grid" style={{ gap: 12, marginTop: 14, minWidth: 0 }} aria-label="人工研究复核">
    <div className="spread" style={{ gap: 8, flexWrap: 'wrap' }}>
      <strong>逐条核对，记录我的选择</strong>
      <button type="button" className="btn btn-sm" disabled={busy || loading} onClick={() => { setRefresh(n => n + 1); setError(''); }}>刷新复核记录</button>
    </div>
    <div className="t-dim" style={{ fontSize: 13 }}>资料截至 {data?.panel_as_of || asOf}。保存的是本次核对的研究意见；原建议和未回复的事项继续保留，研究待办仍需实际完成。</div>
    {data?.summary && <div className="t-dim" role="status">
      本期资料 {data.summary.current} 项 · 历史待核 {data.summary.historical} 项 · 日期待核 {data.summary.unverified} 项；
      当前面板已记录选择 {data.summary.recorded_choices} 项、已追加观察 {data.summary.with_observations} 项。独立结果尚未验证。
    </div>}
    {loadError && <div role="alert">{loadError}</div>}
    {data?.warning && <div role="status">{ERRORS[data.warning] || '当前面板证据不完整，历史复核记录仍可查看。'}</div>}
    {loading && <div role="status">正在读取复核记录…</div>}
    <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
      <label>资料范围 <select aria-label="资料范围" value={period} onChange={e => { setPeriod(e.target.value); setCount(6); }}>
        <option value="current">本期资料</option><option value="historical">历史待核</option>
        <option value="unverified">日期待核</option><option value="all">全部资料</option>
      </select></label>
      <label>类型 <select aria-label="复核类型" value={kind} onChange={e => { setKind(e.target.value); setCount(6); }}>
        <option value="all">全部</option>{Object.entries(KINDS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>
      <label>搜索 <input aria-label="搜索复核事项" value={query} onChange={e => { setQuery(e.target.value); setCount(6); }} style={{ maxWidth: '100%' }} placeholder="代码、名称或理由" /></label>
      <span className="t-faint">{filtered.length} 条</span>
    </div>
    {filtered.slice(0, count).map(item => <article key={item.item_id} className="glass-inset" aria-label={`${KINDS[item.card_type]} ${item.name}`} style={{ padding: 12, minWidth: 0, overflowWrap: 'anywhere' }}>
      <div className="grid" style={{ gap: 8 }}>
        <strong>{KINDS[item.card_type]} · {item.name} {item.name !== item.subject ? item.subject : ''}</strong>
        <div>{item.summary}</div>
        {item.source_scope === 'historical' && <div className="t-dim">历史事项，创建于 {item.source_date}；本次复核不代表原任务完成。</div>}
        {item.source_scope === 'unverified' && <div className="t-dim">来源日期尚未核实，请先查看原始证据。</div>}
        <div className="t-faint">{item.validity === 'expired' ? '资料已过期' : item.expires_at ? `有效至 ${item.expires_at}` : '未提供有效期，请核对当前情况'}</div>
        <Original source={item} />
        {item.review ? <Recorded review={item.review} onOutcome={openOutcome} busy={busy} /> :
          <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>{(Object.keys(CHOICES) as ReviewChoice[]).map(choice =>
            <button key={choice} type="button" className="btn btn-sm" disabled={busy || (choice !== 'rejected' && (item.validity === 'expired' || !item.reviewable))}
              onClick={() => openChoice(item, choice)}>{CHOICES[choice]}</button>)}</div>}
        {editing?.item.item_id === item.item_id && <form className="grid" style={{ gap: 8 }} onSubmit={e => { e.preventDefault(); void submitChoice(); }}>
          <strong>{CHOICES[editing.choice]}这条研究意见</strong>
          <label>我的理由<textarea aria-label="我的理由" required maxLength={4000} value={rationale} onChange={e => setRationale(e.target.value)} style={{ display: 'block', width: '100%', minHeight: 72 }} /></label>
          {editing.choice === 'modified' && <label>修改后的判断<textarea aria-label="修改后的判断" required maxLength={4000} value={revision} onChange={e => setRevision(e.target.value)} style={{ display: 'block', width: '100%', minHeight: 72 }} /></label>}
          <div className="row" style={{ gap: 8 }}><button className="btn btn-primary" type="submit" disabled={busy || !rationale.trim() || (editing.choice === 'modified' && !revision.trim())}>{busy ? '正在保存…' : '保存我的选择'}</button>
            <button className="btn" type="button" disabled={busy} onClick={() => setEditing(null)}>取消</button></div>
        </form>}
      </div>
    </article>)}
    {!loading && data && filtered.length === 0 && <div className="t-faint">当前筛选下没有可复核事项。</div>}
    {filtered.length > count && <button type="button" className="btn" onClick={() => setCount(n => n + 20)}>显示更多事项</button>}
    <details><summary style={{ cursor: 'pointer' }}>已保存记录（最近 {data?.history.length || 0} 条，最多 {data?.history_limit || 100} 条）</summary>
      <div className="grid" style={{ gap: 10, marginTop: 10 }}>{(data?.history || []).map(review =>
        <article key={review.review_id} className="glass-inset" style={{ padding: 12, overflowWrap: 'anywhere' }}>
          <strong>{review.source.name} · 资料日期 {review.source.panel_as_of}</strong><Original source={review.source} /><Recorded review={review} onOutcome={openOutcome} busy={busy} />
        </article>)}</div>
    </details>
    {outcome && <form ref={outcomeForm} className="glass-inset grid" style={{ gap: 8, padding: 12 }} onSubmit={e => { e.preventDefault(); void submitOutcome(); }}>
      <strong>补充 {outcome.review.source.name} 的后续观察</strong>
      <label>观察结果 <select aria-label="观察结果" value={outcomeStatus} onChange={e => setOutcomeStatus(e.target.value as ReviewOutcome)}>{Object.entries(OUTCOMES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>观察说明<textarea aria-label="观察说明" maxLength={4000} required value={outcomeNote} onChange={e => setOutcomeNote(e.target.value)} style={{ display: 'block', width: '100%', minHeight: 72 }} /></label>
      <div className="t-faint">这是一条人工观察记录，不会自动变成已验证记忆或收益结论。</div>
      <div className="row" style={{ gap: 8 }}><button type="submit" className="btn btn-primary" disabled={busy || !outcomeNote.trim()}>保存后续观察</button><button type="button" className="btn" disabled={busy} onClick={() => setOutcome(null)}>取消</button></div>
    </form>}
    {error && <div role="alert">{error}</div>}
  </div>;
}
