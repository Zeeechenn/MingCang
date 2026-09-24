import React, { useEffect, useRef, useState } from 'react';
import { Card } from '../../shared';
import { chatWithAIStream } from '../../services/api';
import { loadResearchContext, loadResearchMessages, loadResearchReviews, loadResearchTaskStatus, prepareResearchTask, saveResearchObservation, saveResearchReview } from '../../services/research-context';
import type { PreparedResearchTask, ResearchContext, ResearchHorizon, ResearchSelection, ResearchSource, ResearchTaskSpec } from '../../services/research-context';

const labels: Record<string, string> = { revenue_yoy: '营收同比', net_profit_yoy: '净利同比', total_assets: '总资产', total_equity: '股东权益', long_term_debt: '长期负债', asset_turnover: '资产周转率', open: '开盘', high: '最高', low: '最低', close: '收盘', volume: '成交量（单位待核）', atr14: 'ATR14', revenue: '营收', net_profit: '净利润', operating_cf: '经营现金流', roe: 'ROE', gross_margin: '毛利率', current_ratio: '流动比率' };
const outcomeLabels = { supported: '观察支持原判断', contradicted: '观察反驳原判断', inconclusive: '证据仍不足', not_observed: '尚未观察到' };
const choiceLabels = { accepted: '接受', modified: '修改后接受', rejected: '拒绝' };
const definitelyNotStartedErrors = [
  'page_evidence_changed_reload_required',
  'invalid_page_question',
  'question_symbol_differs_from_page',
  'research_task_binding_invalid',
  'page_evidence_incomplete',
  'research_provider_unavailable',
  'page_session_mismatch',
];
function priorDay(day: string, days: number) { const d = new Date(`${day}T00:00:00Z`); d.setUTCDate(d.getUTCDate() - days); return d.toISOString().slice(0, 10); }
function failure(error: any) {
  if (/page_evidence_changed/.test(String(error?.message))) return '证据已更新，请重新载入后再提交。';
  if (/page_evidence_incomplete/.test(String(error?.message))) return '资料存在缺口，暂不能向 AI 提问。';
  return error?.message || '请求未完成，请稍后重试。';
}

function preReservationRejection(error: any) {
  const message = String(error?.message || '');
  return definitelyNotStartedErrors.find(code => message === code || message.includes(`"detail":"${code}"`)) || null;
}

function Sources({ rows, prefix }: { rows: ResearchSource[]; prefix: string }) {
  return <div style={{ display: 'grid', gap: 6 }}>
    {rows.map(row => <details key={row.id} id={`${prefix}-${row.id}`} className="glass-inset" style={{ padding: 10, overflowWrap: 'anywhere' }}>
      <summary style={{ cursor: 'pointer', fontSize: 12 }}>{row.kind === 'price' ? '行情' : '财报'} · {row.date} · {row.source || '来源未知'} · 抓取 {row.fetched_at || '时间未知'}</summary>
      <p className="t-faint" style={{ fontSize: 12 }}>{row.id} · {row.currency || '币种未知'} · {row.adjustment || '财务原值'}{row.disclosure_date ? ` · 披露 ${row.disclosure_date}` : ''}</p>
      <dl style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 8, margin: 0 }}>
        {Object.entries(row.values).map(([key, value]) => <div key={key}>
          <dt className="t-dim" style={{ fontSize: 11 }}>{labels[key] || key}</dt>
          <dd style={{ margin: 0, fontSize: 13 }}>{value == null ? '未知' : String(value)} · {row.value_units?.[key] || '单位未知'}</dd>
          <small className="t-faint">{row.value_calculations?.[key] || '存储原值；未计算'}</small>
        </div>)}
      </dl>
    </details>)}
  </div>;
}

function ReviewEvidence({ ids, sources, title, prefix }: { ids: string[]; sources: ResearchSource[]; title: string; prefix: string }) {
  if (!ids?.length) return <p className="t-faint">{title}：未选择</p>;
  return <details><summary>{title}（{ids.length}）</summary>
    <Sources rows={sources.filter(source => ids.includes(source.id))} prefix={prefix} />
  </details>;
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

type StoredRun = {
  request_id: string;
  task: ResearchTaskSpec & { context_sha256: string };
  evidence: ResearchContext;
  prior_judgments: any[];
  session_id: string | null;
  terminal_execution?: Record<string, any>;
};

function requestId() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function taskStateLabel(state?: string) {
  if (state === 'submitting' || state === 'running' || state === 'reserved_unknown') return '请求已提交，远端处理中或结果尚待确认';
  if (state === 'completed' || state === 'executed') return '请求已完成';
  if (state === 'failed') return '请求失败';
  if (state === 'unknown_remote_completion') return '请求未完成，远端结果未知';
  if (state === 'unknown' || state === 'checking') return '远端状态未知';
  if (state === 'rejected_not_started') return '请求已明确拒绝，研究未开始；请重新准备';
  return state || '尚未提交';
}

function horizonLabel(value?: string) {
  return value === 'short' ? '短期' : value === 'long' ? '长期' : '中期';
}

function remoteOutcomeLabel(value?: string) {
  if (value === 'not_started') return '未发起研究';
  if (value === 'completed') return '已返回';
  if (value === 'completed_invalid_output') return '已返回，但结果格式无效';
  if (value === 'unknown') return '未知';
  return value || '未知';
}

function executionErrorLabel(value?: string) {
  if (value === 'research_provider_failed') return '研究服务返回异常，远端结果尚未确认';
  if (value === 'unknown_remote_completion') return '请求未完成，远端结果未知';
  return value || '';
}

function PriorJudgments({ rows }: { rows: any[] }) {
  if (!rows.length) return <p className="t-dim">所选截止日前没有可展示的历史人工判断。</p>;
  return <div style={{ display: 'grid', gap: 6 }}>
    {rows.map((row, index) => <details key={row.review_id || index} className="glass-inset" style={{ padding: 10 }}>
      <summary>历史人工判断 · {row.decision_as_of || '日期未知'} · {row.validity === 'same_evidence_context' ? '证据版本相同' : '证据版本已变化'}</summary>
      <p>{row.decision?.judgment || row.decision?.choice || '判断内容未知'}</p>
      {row.decision?.rationale && <p>当时理由：{row.decision.rationale}</p>}
      <small className="t-faint">记录于 {row.recorded_at || '时间未知'} · 历史人工判断，不是当前事实</small>
      {(row.outcomes || []).map((outcome: any) => <p key={outcome.observation_id}>后续观察：{outcome.note} · {outcome.status} · 人工记录，未经独立核验</p>)}
    </details>)}
  </div>;
}

export function EvidenceWorkspace({ symbol, endDate, enabled }: { symbol: string; endDate?: string; enabled: boolean }) {
  const day = endDate || priorDay(new Date().toISOString().slice(0, 10), 1);
  const [start, setStart] = useState(priorDay(day, 90)); const [end, setEnd] = useState(day);
  const [context, setContext] = useState<ResearchContext | null>(null); const [reload, setReload] = useState(0);
  const [restoring, setRestoring] = useState(false);
  const [restoreFailed, setRestoreFailed] = useState(false); const [historyReload, setHistoryReload] = useState(0);
  const [loading, setLoading] = useState(false); const [busy, setBusy] = useState(false); const [prepareBusy, setPrepareBusy] = useState(false); const [error, setError] = useState('');
  const [question, setQuestion] = useState(''); const [horizon, setHorizon] = useState<ResearchHorizon>('medium'); const [budgetTokens, setBudgetTokens] = useState(900);
  const [prepared, setPrepared] = useState<PreparedResearchTask | null>(null);
  const [answers, setAnswers] = useState<any[]>([]); const [reviews, setReviews] = useState<any[]>([]);
  const [judgment, setJudgment] = useState(''); const [rationale, setRationale] = useState(''); const [watchFor, setWatchFor] = useState('');
  const [choice, setChoice] = useState<'accepted' | 'modified' | 'rejected'>('modified'); const [revisedText, setRevisedText] = useState('');
  const [supportingIds, setSupportingIds] = useState<string[]>([]); const [contradictingIds, setContradictingIds] = useState<string[]>([]); const [uncertainties, setUncertainties] = useState('');
  const [activeRun, setActiveRun] = useState<StoredRun | null>(null); const [taskExecution, setTaskExecution] = useState<any>(null); const [phase, setPhase] = useState(''); const [localStopped, setLocalStopped] = useState(false);
  const [statusReload, setStatusReload] = useState(0);
  const generation = useRef(0); const session = useRef<string | null>(null); const abortController = useRef<AbortController | null>(null);
  const requestStorageKey = `mc_research_request_${symbol}`;
  const selection: ResearchSelection = { symbol, market: 'CN', start, as_of: end, adjustment: 'stored' };
  const current = context && Object.entries(selection).every(([k, v]) => context.selection[k] === v) ? context : null;
  const preparedMatches = Boolean(prepared && current
    && prepared.task.context_sha256 === current.context_sha256
    && prepared.task.question === question.trim()
    && prepared.task.horizon === horizon
    && prepared.task.budget_tokens === budgetTokens);
  const executionState = taskExecution?.state || taskExecution?.status;
  const taskPending = Boolean(activeRun && !['completed', 'executed', 'failed', 'rejected_not_started'].includes(executionState));

  useEffect(() => {
    const seq = ++generation.current; let active = true;
    setPrepared(null); setPhase('');
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
  useEffect(() => {
    setActiveRun(null); setTaskExecution(null); setLocalStopped(false);
    if (!enabled) return;
    try {
      const raw = localStorage.getItem(requestStorageKey);
      if (!raw) return;
      const saved = JSON.parse(raw) as StoredRun;
      if (!saved.request_id || !saved.task?.context_sha256) return;
      setActiveRun(saved); setQuestion(saved.task.question); setHorizon(saved.task.horizon); setBudgetTokens(saved.task.budget_tokens);
      setTaskExecution(saved.terminal_execution || { state: 'checking', request_id: saved.request_id, retry_allowed: false, remote_outcome: 'unknown' });
    } catch {
      setTaskExecution({ state: 'unknown', error: 'saved_request_state_unreadable', retry_allowed: false, remote_outcome: 'unknown' });
    }
  }, [symbol, enabled, requestStorageKey]);
  useEffect(() => {
    if (!enabled || !activeRun || activeRun.terminal_execution?.state === 'rejected_not_started') return;
    let active = true; let timer: ReturnType<typeof setTimeout> | undefined;
    const applyStatus = (status: any) => {
      if (!active) return;
      const execution = status.execution || {};
      setTaskExecution({ ...execution, state: execution.state || status.status, request_id: status.request_id, input_sha256: status.input_sha256 });
      if (status.response) {
        const response = status.response;
        if (response.session_id) {
          session.current = response.session_id;
          localStorage.setItem(`mc_research_session_${symbol}`, response.session_id);
        }
        setAnswers(old => old.some(a => a.task_execution?.request_id === activeRun.request_id)
          ? old : [...old, { ...response, question: activeRun.task.question, snapshot: activeRun.evidence }]);
      }
    };
    const poll = async () => {
      try {
        const status = await loadResearchTaskStatus(activeRun.request_id);
        applyStatus(status);
        if (status.status === 'running') timer = setTimeout(poll, 1500);
      } catch (e: any) {
        if (!active) return;
        const msg = String(e?.message || 'status_unavailable');
        setTaskExecution(old => ({ ...(old || {}), state: 'unknown', request_id: activeRun.request_id, remote_outcome: 'unknown', retry_allowed: false, status_error: msg }));
        // The original POST may still be reaching its reservation commit. Poll by the same id only.
        timer = setTimeout(poll, 2500);
      }
    };
    timer = setTimeout(poll, 1000);
    return () => { active = false; if (timer) clearTimeout(timer); };
  }, [activeRun, activeRun?.terminal_execution?.state, enabled, symbol, statusReload]);

  async function prepare() {
    if (!current || !question.trim()) return;
    setPrepareBusy(true); setError(''); setPrepared(null);
    const spec: ResearchTaskSpec = { ...current.selection, question: question.trim(), horizon, budget_tokens: budgetTokens, max_calls: 1 };
    try {
      const result = await prepareResearchTask(spec);
      if (result.evidence.context_sha256 !== current.context_sha256) throw new Error('准备结果的证据版本与当前页面不一致，请重新载入。');
      setPrepared(result);
    } catch (e) { setError(failure(e)); } finally { setPrepareBusy(false); }
  }

  async function ask() {
    if (!current || !current.can_ask || !preparedMatches || !prepared?.can_ask || taskPending || restoring || restoreFailed) return;
    const snapshot = current; const spec = prepared.task; const id = requestId();
    const run: StoredRun = { request_id: id, task: spec, evidence: prepared.evidence, prior_judgments: prepared.prior_judgments || [], session_id: session.current };
    // Persist before POST. Refresh always resumes with GET status and never replays the model POST.
    localStorage.setItem(requestStorageKey, JSON.stringify(run)); setActiveRun(run); setLocalStopped(false);
    setBusy(true); setError(''); setPhase('正在建立流式连接'); setTaskExecution({ state: 'submitting', request_id: id, max_calls: 1, retry_allowed: false, remote_outcome: 'unknown' });
    const controller = new AbortController(); abortController.current = controller;
    try {
      const binding = { ...snapshot.selection, context_sha256: snapshot.context_sha256 };
      const result: any = await chatWithAIStream({ message: spec.question, mode: 'general', session_id: session.current,
        research_context: binding, research_task: spec, request_id: id }, {
        signal: controller.signal,
        onPrepare: () => setPhase('服务端已接收流连接；正在核对任务状态'),
        onRunning: event => setPhase(event.stage || '远端研究正在运行'),
        onEvidence: () => setPhase('正在组织本次证据'),
        onError: data => { throw new Error(data.message || 'remote_stream_error'); },
      });
      if (result?.research_context?.context_sha256 !== snapshot.context_sha256) throw new Error('回答未绑定所选证据。');
      if (result?.session_id) {
        session.current = result.session_id;
        localStorage.setItem(`mc_research_session_${symbol}`, result.session_id);
        const savedRun = { ...run, session_id: result.session_id };
        localStorage.setItem(requestStorageKey, JSON.stringify(savedRun)); setActiveRun(savedRun);
      }
      setAnswers(old => old.some(a => a.task_execution?.request_id === id) ? old : [...old, { ...result, question: spec.question, snapshot }]);
      if (result?.task_execution) setTaskExecution(result.task_execution);
      setPhase(result ? '研究回答已保存，可从 request_id 恢复' : '流结束但未收到最终结果；正在按 request_id 查询状态');
      setPrepared(null);
    } catch (e: any) {
      if (e?.name === 'AbortError') {
        setLocalStopped(true); setPhase('已停止本地等待；远端是否完成未知，正在按 request_id 查询，不会重新提交。');
        setTaskExecution(old => ({ ...(old || {}), state: 'unknown', remote_outcome: 'unknown', retry_allowed: false }));
      } else {
        const rejection = preReservationRejection(e);
        if (rejection) {
          const terminal = { state: 'rejected_not_started', request_id: id, logical_provider_invocations: 0,
            max_calls: 1, remote_outcome: 'not_started', retry_allowed: false, error: rejection };
          const savedRun = { ...run, terminal_execution: terminal };
          localStorage.setItem(requestStorageKey, JSON.stringify(savedRun)); setActiveRun(savedRun);
          setPrepared(null); setTaskExecution(terminal); setPhase('服务端确认拒绝发生在研究预留之前；没有发起模型调用。请重新准备后再提交。');
          setError(failure(e));
        } else {
          setError(failure(e)); setPhase('提交结果未在流中确认；状态检查不会重新提交。');
          setTaskExecution(old => ({ ...(old || {}), state: 'unknown', remote_outcome: 'unknown', retry_allowed: false, last_error: failure(e) }));
        }
      }
    } finally { setBusy(false); abortController.current = null; }
  }

  async function record() {
    if (!current) return; setBusy(true); setError('');
    try {
      const saved: any = await saveResearchReview({ context: { ...current.selection, context_sha256: current.context_sha256 }, judgment, rationale, watch_for: watchFor,
        choice, revised_text: choice === 'modified' ? revisedText : '', supporting_evidence_ids: supportingIds,
        contradicting_evidence_ids: contradictingIds, uncertainties: uncertainties.split('\n').map(v => v.trim()).filter(Boolean) });
      setReviews(old => [saved, ...old.filter(r => r.review_id !== saved.review_id)]);
      setJudgment(''); setRationale(''); setWatchFor(''); setRevisedText(''); setSupportingIds([]); setContradictingIds([]); setUncertainties('');
    } catch (e) { setError(failure(e)); } finally { setBusy(false); }
  }
  function toggleEvidence(id: string, list: string[], setList: (next: string[]) => void) {
    setList(list.includes(id) ? list.filter(value => value !== id) : [...list, id]);
  }
  function stopLocalWait() {
    setLocalStopped(true); setPhase('已停止本地等待；远端结果未知，状态仍会通过 request_id 查询。');
    abortController.current?.abort(); setBusy(false);
  }
  const alreadySaved = reviews.some(r => r.source.context_sha256 === current?.context_sha256);
  const preparedReady = current?.can_ask && preparedMatches && prepared?.can_ask && !taskPending;
  const runResponse = taskExecution?.response;
  return <Card title="基于本页证据研究" eyebrow="资料 → 提问 → 判断 → 后续观察">
    {!enabled ? <p className="t-dim">连接真实后端后，可载入同一版本的资料、提问并保存判断。演示数据不提交研究记录。</p> : <div style={{ display: 'grid', gap: 12 }}>
      <p className="t-dim" style={{ margin: 0 }}>以下研究区单独绑定股票和日期。页面其他卡片仍展示其原始日期；AI 只读取本区的行情与财务资料。</p>
      <div className="row" style={{ flexWrap: 'wrap', gap: 10 }}>
        <label>起始日<input className="input" aria-label="证据起始日" type="date" value={start} onChange={e => { setStart(e.target.value); setPrepared(null); }} disabled={busy || prepareBusy} /></label>
        <label>截止日<input className="input" aria-label="证据截止日" type="date" value={end} onChange={e => { setEnd(e.target.value); setPrepared(null); }} disabled={busy || prepareBusy} /></label>
        <button className="btn btn-sm" onClick={() => setReload(v => v + 1)} disabled={busy || prepareBusy || loading}>重新载入证据</button>
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
        <label>研究问题<textarea aria-label="本页研究问题" className="input" style={{ width: '100%', minHeight: 75 }} value={question} maxLength={2000} onChange={e => { setQuestion(e.target.value); setPrepared(null); }} placeholder="例如：当前现金流能否支持利润增长？还缺哪些资料？" /></label>
        <div className="row" style={{ flexWrap: 'wrap', gap: 10 }}>
          <label>研究期限<select aria-label="研究期限" className="input" value={horizon} onChange={e => { setHorizon(e.target.value as ResearchHorizon); setPrepared(null); }} disabled={busy || prepareBusy}>
            <option value="short">短期</option><option value="medium">中期</option><option value="long">长期</option>
          </select></label>
          <label>输出 token 上限<input aria-label="输出token上限" className="input" type="number" min={64} max={900} step={1} value={budgetTokens} onChange={e => { setBudgetTokens(Math.max(64, Math.min(900, Number(e.target.value) || 64))); setPrepared(null); }} disabled={busy || prepareBusy} /></label>
          <button className="btn btn-sm" onClick={prepare} disabled={prepareBusy || busy || restoring || restoreFailed || !current || !question.trim()}>{prepareBusy ? '正在准备…' : '准备本次研究'}</button>
        </div>
        <small className="t-faint">准备阶段不调用 AI；输出 token 上限不是总用量或费用上限。每个任务只发起一次研究，服务商内部重试次数与实际费用未知。</small>
        {prepared && preparedMatches && <div className="glass-inset" style={{ padding: 10 }}>
          <b>{prepared.can_ask ? '准备完成：0 次模型调用' : '准备发现证据缺口，不能提交研究'}</b>
          <p className="t-faint">绑定证据版本 {prepared.task.context_sha256.slice(0, 10)} · 截止 {prepared.task.as_of} · 期限 {horizonLabel(prepared.task.horizon)} · 输出上限 {prepared.task.budget_tokens}</p>
          <details><summary>历史人工判断（不作为事实）</summary><PriorJudgments rows={prepared.prior_judgments || []} /></details>
        </div>}
        <button className="btn btn-primary" disabled={!preparedReady || busy || restoring || restoreFailed} onClick={ask}>{busy ? '远端处理中…' : '开始本次研究'}</button>
        {!current.can_ask && <p className="t-dim">先补齐上方资料缺口。准备操作只读取并标明缺口，不调用模型；可以记录待核实判断。</p>}
        {activeRun && taskExecution && <div className="glass-inset" role="status" style={{ padding: 10 }}>
          <b>{taskStateLabel(executionState)}</b>
          <small className="t-faint">任务编号：{activeRun.request_id}</small>
          <p>本次研究调用：{Number.isInteger(taskExecution.logical_provider_invocations) ? taskExecution.logical_provider_invocations : '待确认'} / {taskExecution.max_calls ?? 1} · 服务商请求次数：{taskExecution.provider_wire_attempts && !String(taskExecution.provider_wire_attempts).startsWith('unknown') ? taskExecution.provider_wire_attempts : '未知（可能内部重试）'}</p>
          {taskExecution.remote_outcome && <p>远端结果：{remoteOutcomeLabel(taskExecution.remote_outcome)}</p>}
          {(taskExecution.error || taskExecution.last_error || taskExecution.status_error) && <div role="alert">原因：{executionErrorLabel(taskExecution.error || taskExecution.last_error || taskExecution.status_error)}
            <details><summary>查看错误代码</summary><code>{taskExecution.error || taskExecution.last_error || taskExecution.status_error}</code></details>
          </div>}
          {phase && <p>{phase}</p>}
          {localStopped && <p>停止的是本地等待，未发送远端取消请求；远端可能仍在运行或已经完成。</p>}
          {busy && <button className="btn btn-sm" onClick={stopLocalWait}>停止本地等待</button>}
          {!busy && executionState === 'unknown' && <button className="btn btn-sm" onClick={() => { setTaskExecution(old => ({ ...(old || {}), state: 'checking' })); setStatusReload(v => v + 1); }}>重新查询远端状态</button>}
          {runResponse?.answer && <p style={{ whiteSpace: 'pre-wrap' }}>{runResponse.answer}</p>}
        </div>}
      </>}
      {answers.map((a, index) => <article className="glass-inset" key={a.task_execution?.request_id || index} style={{ padding: 12, overflowWrap: 'anywhere' }}>
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
          <label>选择<select aria-label="判断选择" className="input" value={choice} onChange={e => setChoice(e.target.value as typeof choice)}><option value="accepted">接受</option><option value="modified">修改后接受</option><option value="rejected">拒绝</option></select></label>
          <input className="input" aria-label="我的判断" value={judgment} maxLength={2000} onChange={e => setJudgment(e.target.value)} placeholder="记录自己的结论" />
          {choice === 'modified' && <textarea className="input" aria-label="修改后的判断" value={revisedText} maxLength={2000} onChange={e => setRevisedText(e.target.value)} placeholder="写明修改后的判断" />}
          <textarea className="input" aria-label="判断依据" value={rationale} maxLength={2000} onChange={e => setRationale(e.target.value)} placeholder="支持判断的证据和仍不确定的部分" />
          <details className="glass-inset" style={{ padding: 10 }}><summary>选择支持与反对证据</summary>
            {current.sources.map(source => <div key={source.id} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 6 }}>
              <small>{source.date} · {source.source || '来源未知'} · {source.id}</small>
              <label><input type="checkbox" aria-label={`支持 ${source.id}`} checked={supportingIds.includes(source.id)} onChange={() => {
                toggleEvidence(source.id, supportingIds, setSupportingIds);
                setContradictingIds(old => old.filter(value => value !== source.id));
              }} />支持</label>
              <label><input type="checkbox" aria-label={`反对 ${source.id}`} checked={contradictingIds.includes(source.id)} onChange={() => {
                toggleEvidence(source.id, contradictingIds, setContradictingIds);
                setSupportingIds(old => old.filter(value => value !== source.id));
              }} />反对</label>
            </div>)}
          </details>
          <textarea className="input" aria-label="不确定事项" value={uncertainties} maxLength={2000} onChange={e => setUncertainties(e.target.value)} placeholder="逐行填写仍不确定的问题" />
          <textarea className="input" aria-label="后续验证条件" value={watchFor} maxLength={2000} onChange={e => setWatchFor(e.target.value)} placeholder="下次验证：未来看到什么会支持或推翻判断？" />
          <button className="btn btn-sm" onClick={record} disabled={!judgment.trim() || !rationale.trim() || !watchFor.trim() || !current.sources.length || (choice === 'modified' && !revisedText.trim())}>{alreadySaved ? '该证据版本已保存判断' : '保存判断与证据'}</button>
        </div>
      </fieldset>}
      <small className="t-faint">保存判断与追加观察不会下单、修改仓位或更新策略记忆；观察不等于已核实收益。</small>
      {reviews.map(review => <details className="glass-inset" style={{ padding: 12 }} key={review.review_id}>
        <summary>{review.source.selection.as_of} · {choiceLabels[review.result.human_choice?.choice as keyof typeof choiceLabels] || '判断'} · {review.result.decision.judgment}</summary>
        <p>当时理由：{review.result.decision.rationale}</p><p>修改后判断：{review.result.human_choice?.revised_text || '无'}</p><p>下次验证：{review.result.decision.watch_for}</p>
        {review.result.human_choice?.uncertainties?.length > 0 && <p>不确定事项：{review.result.human_choice.uncertainties.join('；')}</p>}
        <ReviewEvidence ids={review.result.human_choice?.supporting_evidence_ids || []} sources={review.source.sources} title="支持证据" prefix={`${review.review_id}-support`} />
        <ReviewEvidence ids={review.result.human_choice?.contradicting_evidence_ids || []} sources={review.source.sources} title="反对证据" prefix={`${review.review_id}-against`} />
        <details><summary>查看当时保存的证据</summary><Sources rows={review.source.sources} prefix={review.review_id} /></details>
        <Observation review={review} onSaved={row => setReviews(old => old.map(r => r.review_id === row.review_id ? row : r))} />
      </details>)}
    </div>}
  </Card>;
}
