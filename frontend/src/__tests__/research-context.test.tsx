import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { EvidenceWorkspace } from '../features/research/EvidenceWorkspace';
import { loadResearchContext, loadResearchMessages, loadResearchReviews, loadResearchTaskStatus, prepareResearchTask, saveResearchReview } from '../services/research-context';
import { chatWithAIStream } from '../services/api';

vi.mock('../services/research-context', () => ({ loadResearchContext: vi.fn(), loadResearchReviews: vi.fn(), loadResearchMessages: vi.fn(), loadResearchTaskStatus: vi.fn(), prepareResearchTask: vi.fn(), saveResearchReview: vi.fn(), saveResearchObservation: vi.fn() }));
vi.mock('../services/api', () => ({ chatWithAIStream: vi.fn() }));
const source = { id: 'price-1', kind: 'price', date: '2026-09-15', source: 'fixture', adjustment: 'qfq', currency: 'CNY', fetched_at: null, values: { close: 11 }, value_units: { close: 'CNY/share' }, value_calculations: { close: 'stored value' } };
const make = (selection: any) => ({ selection, context_sha256: selection.as_of === '2026-09-15' ? 'a'.repeat(64) : 'b'.repeat(64), sources: [source], gaps: [], limitations: ['合成测试证据'], can_ask: true });
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear();
  vi.mocked(loadResearchContext).mockImplementation(async s => make(s));
  vi.mocked(loadResearchReviews).mockResolvedValue({ reviews: [] });
  vi.mocked(loadResearchMessages).mockResolvedValue([]);
  vi.mocked(prepareResearchTask).mockImplementation(async (task: any) => {
    const evidence = make(task);
    return { schema_version: 'research_task.v1', task: { ...task, context_sha256: evidence.context_sha256 }, evidence,
      prior_judgments: [], execution: { mode: 'prepare_only', model_calls: 0, max_calls: 1, budget_tokens: task.budget_tokens }, can_ask: evidence.can_ask };
  });
  vi.mocked(loadResearchTaskStatus).mockResolvedValue({ request_id: 'pending', status: 'executed',
    execution: { state: 'completed', logical_provider_invocations: 1, max_calls: 1, remote_outcome: 'completed' } });
  vi.mocked(chatWithAIStream).mockImplementation(async (p: any) => ({ answer: '合成研究回答', research_context: p.research_context,
    research_claims: [{ text: '合成研究回答', evidence_ids: ['price-1'] }], session_id: 'page-session' }));
});

it('sends exactly the displayed binding and marks an old answer after date changes', async () => {
  render(<EvidenceWorkspace symbol="600001" endDate="2026-09-15" enabled />);
  await screen.findByText(/版本 aaaaaaaaaa/);
  fireEvent.change(screen.getByLabelText('本页研究问题'), { target: { value: '现金流如何？' } });
  fireEvent.click(screen.getByText('准备本次研究'));
  await screen.findByText('准备完成：0 次模型调用');
  fireEvent.click(screen.getByText('开始本次研究'));
  await screen.findByText('合成研究回答');
  expect(prepareResearchTask).toHaveBeenCalledWith(expect.objectContaining({ question: '现金流如何？', horizon: 'medium', budget_tokens: 900, max_calls: 1 }));
  expect(vi.mocked(chatWithAIStream).mock.calls[0][0].research_context).toMatchObject({ symbol: '600001', as_of: '2026-09-15', context_sha256: 'a'.repeat(64) });
  expect(vi.mocked(chatWithAIStream).mock.calls[0][0]).toMatchObject({ research_task: expect.objectContaining({ question: '现金流如何？', context_sha256: 'a'.repeat(64) }), request_id: expect.any(String) });
  fireEvent.change(screen.getByLabelText('证据截止日'), { target: { value: '2026-09-14' } });
  await screen.findByText(/版本 bbbbbbbbbb/);
  expect(screen.getByText(/不适用于当前选择/)).toBeInTheDocument();
  expect(saveResearchReview).not.toHaveBeenCalled();
});

it('shows source timestamps, explicit units, and calculation notes', async () => {
  render(<EvidenceWorkspace symbol="600001" endDate="2026-09-15" enabled />);
  await screen.findByText(/版本 aaaaaaaaaa/);
  fireEvent.click(screen.getByText('查看本页原始证据'));
  fireEvent.click(screen.getByText(/行情 · 2026-09-15/));
  expect(screen.getByText(/抓取 时间未知/)).toBeInTheDocument();
  expect(screen.getByText(/11 · CNY\/share/)).toBeInTheDocument();
  expect(screen.getByText('stored value')).toBeInTheDocument();
});

it('never accepts a slow response from the previous selection', async () => {
  let resolveOld: (value: any) => void = () => {};
  vi.mocked(loadResearchContext).mockImplementationOnce(() => new Promise(r => { resolveOld = r; }));
  render(<EvidenceWorkspace symbol="600001" endDate="2026-09-15" enabled />);
  fireEvent.change(screen.getByLabelText('证据截止日'), { target: { value: '2026-09-14' } });
  await screen.findByText(/版本 bbbbbbbbbb/);
  await act(async () => resolveOld(make({ symbol: '600001', market: 'CN', start: '2026-06-17', as_of: '2026-09-15', adjustment: 'stored' })));
  expect(screen.queryByText(/版本 aaaaaaaaaa/)).not.toBeInTheDocument();
});

it('shows data gaps and keeps model calls disabled', async () => {
  vi.mocked(loadResearchContext).mockImplementation(async s => ({ ...make(s), gaps: ['财报已过期'], can_ask: false }));
  vi.mocked(prepareResearchTask).mockImplementationOnce(async (task: any) => {
    const evidence = { ...make(task), gaps: ['财报已过期'], can_ask: false };
    return { schema_version: 'research_task.v1', task: { ...task, context_sha256: evidence.context_sha256 }, evidence,
      prior_judgments: [], execution: { mode: 'prepare_only', model_calls: 0, max_calls: 1, budget_tokens: task.budget_tokens }, can_ask: false };
  });
  render(<EvidenceWorkspace symbol="600001" endDate="2026-09-15" enabled />);
  await screen.findByText('财报已过期');
  fireEvent.change(screen.getByLabelText('本页研究问题'), { target: { value: '如何？' } });
  fireEvent.click(screen.getByText('准备本次研究'));
  await screen.findByText('准备发现证据缺口，不能提交研究');
  expect(screen.getByText('开始本次研究')).toBeDisabled();
  expect(chatWithAIStream).not.toHaveBeenCalled();
});

it('persists a judgment only after explicit submission and keeps evidence', async () => {
  vi.mocked(saveResearchReview).mockImplementation(async (p: any) => ({ review_id: 'record-1', source: make(p.context), result: { version: 1, decision: p,
    human_choice: { choice: p.choice, revised_text: p.revised_text, supporting_evidence_ids: p.supporting_evidence_ids,
      contradicting_evidence_ids: p.contradicting_evidence_ids, uncertainties: p.uncertainties }, outcomes: [] } }));
  render(<EvidenceWorkspace symbol="600001" endDate="2026-09-15" enabled />);
  await screen.findByText(/版本 aaaaaaaaaa/);
  fireEvent.change(screen.getByLabelText('我的判断'), { target: { value: '等待核实' } });
  fireEvent.change(screen.getByLabelText('判断选择'), { target: { value: 'accepted' } });
  fireEvent.change(screen.getByLabelText('判断依据'), { target: { value: '现金流资料不足' } });
  fireEvent.change(screen.getByLabelText('后续验证条件'), { target: { value: '核验下次公告' } });
  fireEvent.change(screen.getByLabelText('不确定事项'), { target: { value: '量纲不明' } });
  fireEvent.click(screen.getByText('选择支持与反对证据'));
  fireEvent.click(screen.getByLabelText('支持 price-1'));
  expect(saveResearchReview).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('保存判断与证据'));
  await waitFor(() => expect(saveResearchReview).toHaveBeenCalledTimes(1));
  expect(vi.mocked(saveResearchReview).mock.calls[0][0]).toMatchObject({
    choice: 'accepted', supporting_evidence_ids: ['price-1'], uncertainties: ['量纲不明'],
    context: { context_sha256: 'a'.repeat(64) },
  });
  await screen.findByText('下次验证：核验下次公告');
  expect(screen.getByText(/接受 · 等待核实/)).toBeInTheDocument();
  expect(screen.getByText('支持证据（1）')).toBeInTheDocument();
  expect(screen.getByText('不确定事项：量纲不明')).toBeInTheDocument();
  fireEvent.click(screen.getByText('支持证据（1）'));
  expect(screen.getAllByText(/行情 · 2026-09-15/).length).toBeGreaterThan(1);
});

it('demo mode performs no backend requests', () => {
  render(<EvidenceWorkspace symbol="600001" endDate="2026-09-15" enabled={false} />);
  expect(screen.getByText(/演示数据不提交研究记录/)).toBeInTheDocument();
  expect(loadResearchContext).not.toHaveBeenCalled();
});

it('waits for saved session restoration before sending a new question', async () => {
  localStorage.setItem('mc_research_session_600001', 'saved-session');
  let finish: (value: any[]) => void = () => {};
  vi.mocked(loadResearchMessages).mockImplementationOnce(() => new Promise(r => { finish = r; }));
  render(<EvidenceWorkspace symbol="600001" endDate="2026-09-15" enabled />);
  await screen.findByText(/版本 aaaaaaaaaa/);
  fireEvent.change(screen.getByLabelText('本页研究问题'), { target: { value: '核验现金流' } });
  expect(screen.getByText('开始本次研究')).toBeDisabled();
  await act(async () => finish([]));
  fireEvent.click(screen.getByText('准备本次研究'));
  await screen.findByText('准备完成：0 次模型调用');
  fireEvent.click(screen.getByText('开始本次研究'));
  await screen.findByText('合成研究回答');
  expect(vi.mocked(chatWithAIStream).mock.calls[0][0].session_id).toBe('saved-session');
});

it('waits for existing judgments before enabling a new record', async () => {
  let finish: (value: any) => void = () => {};
  vi.mocked(loadResearchReviews).mockImplementationOnce(() => new Promise(r => { finish = r; }));
  render(<EvidenceWorkspace symbol="600001" endDate="2026-09-15" enabled />);
  await screen.findByText(/版本 aaaaaaaaaa/);
  expect(screen.getByLabelText('我的判断')).toBeDisabled();
  const selection = { symbol: '600001', market: 'CN', start: '2026-06-17', as_of: '2026-09-15', adjustment: 'stored' };
  await act(async () => finish({ reviews: [{ review_id: 'saved-1', source: make(selection), result: { version: 1,
    decision: { judgment: '已保存', rationale: '当时证据', watch_for: '后续公告' }, outcomes: [] } }] }));
  expect(screen.getByText('该证据版本已保存判断')).toBeDisabled();
  expect(saveResearchReview).not.toHaveBeenCalled();
});

it('keeps writes disabled after history failure until an explicit successful retry', async () => {
  vi.mocked(loadResearchReviews).mockRejectedValueOnce(new Error('offline'));
  render(<EvidenceWorkspace symbol="600001" endDate="2026-09-15" enabled />);
  await screen.findByText(/历史记录未能完整读取/);
  expect(screen.getByLabelText('我的判断')).toBeDisabled();
  fireEvent.change(screen.getByLabelText('本页研究问题'), { target: { value: '核验资料' } });
  expect(screen.getByText('准备本次研究')).toBeDisabled();
  fireEvent.click(screen.getByText('重新载入历史记录'));
  await waitFor(() => expect(screen.getByLabelText('我的判断')).not.toBeDisabled());
  expect(screen.getByText('准备本次研究')).not.toBeDisabled();
});

it('restores a saved task by request status and never resubmits after refresh', async () => {
  const selection = { symbol: '600001', market: 'CN', start: '2026-06-17', as_of: '2026-09-15', adjustment: 'stored' };
  const evidence = make(selection);
  localStorage.setItem('mc_research_request_600001', JSON.stringify({ request_id: 'saved-request',
    task: { ...selection, question: '恢复状态', horizon: 'medium', budget_tokens: 300, max_calls: 1, context_sha256: evidence.context_sha256 },
    evidence, prior_judgments: [], session_id: null }));
  vi.mocked(loadResearchTaskStatus).mockResolvedValue({ request_id: 'saved-request', status: 'running',
    execution: { state: 'running', logical_provider_invocations: 1, max_calls: 1, remote_outcome: 'unknown' } });
  render(<EvidenceWorkspace symbol="600001" endDate="2026-09-15" enabled />);
  await waitFor(() => expect(loadResearchTaskStatus).toHaveBeenCalledWith('saved-request'), { timeout: 3000 });
  expect(await screen.findByText(/saved-request/, {}, { timeout: 3000 })).toBeInTheDocument();
  expect(chatWithAIStream).not.toHaveBeenCalled();
});

it('translates an uncertain provider failure and keeps its remote outcome explicit', async () => {
  const selection = { symbol: '600001', market: 'CN', start: '2026-06-17', as_of: '2026-09-15', adjustment: 'stored' };
  const evidence = make(selection);
  localStorage.setItem('mc_research_request_600001', JSON.stringify({ request_id: 'failed-request',
    task: { ...selection, question: '检查失败状态', horizon: 'medium', budget_tokens: 300, max_calls: 1, context_sha256: evidence.context_sha256 },
    evidence, prior_judgments: [], session_id: null }));
  vi.mocked(loadResearchTaskStatus).mockResolvedValue({ request_id: 'failed-request', status: 'failed',
    execution: { state: 'unknown_remote_completion', logical_provider_invocations: 1, max_calls: 1,
      remote_outcome: 'unknown', error: 'research_provider_failed' } });
  render(<EvidenceWorkspace symbol="600001" endDate="2026-09-15" enabled />);
  expect(await screen.findByText('请求未完成，远端结果未知', {}, { timeout: 3000 })).toBeInTheDocument();
  expect(await screen.findByText(/原因：研究服务返回异常，远端结果尚未确认/)).toBeInTheDocument();
  expect(chatWithAIStream).not.toHaveBeenCalled();
});

it('persists a whitelisted pre-reservation rejection and requires a fresh prepare after reload', async () => {
  vi.mocked(chatWithAIStream).mockRejectedValueOnce(new Error('409: {"detail":"page_evidence_changed_reload_required"}'));
  const first = render(<EvidenceWorkspace symbol="600001" endDate="2026-09-15" enabled />);
  await screen.findByText(/版本 aaaaaaaaaa/);
  fireEvent.change(screen.getByLabelText('本页研究问题'), { target: { value: '验证预留前拒绝' } });
  fireEvent.click(screen.getByText('准备本次研究'));
  await screen.findByText('准备完成：0 次模型调用');
  fireEvent.click(screen.getByText('开始本次研究'));
  expect(await screen.findByText(/请求已明确拒绝，研究未开始/)).toBeInTheDocument();
  expect(screen.getByText(/本次研究调用：0 \/ 1/)).toBeInTheDocument();
  expect(screen.getByText(/请重新准备后再提交/)).toBeInTheDocument();
  expect(screen.getByText('准备本次研究')).toBeEnabled();
  expect(screen.getByText('开始本次研究')).toBeDisabled();
  const saved = JSON.parse(localStorage.getItem('mc_research_request_600001') || '{}');
  expect(saved.terminal_execution).toMatchObject({ state: 'rejected_not_started', logical_provider_invocations: 0, error: 'page_evidence_changed_reload_required' });
  await act(async () => new Promise(resolve => setTimeout(resolve, 1100)));
  expect(loadResearchTaskStatus).not.toHaveBeenCalled();

  first.unmount();
  render(<EvidenceWorkspace symbol="600001" endDate="2026-09-15" enabled />);
  expect(await screen.findByText(/请求已明确拒绝，研究未开始/)).toBeInTheDocument();
  expect(screen.getByText('准备本次研究')).toBeEnabled();
  expect(loadResearchTaskStatus).not.toHaveBeenCalled();
  expect(chatWithAIStream).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByText('准备本次研究'));
  await screen.findByText('准备完成：0 次模型调用');
  fireEvent.click(screen.getByText('开始本次研究'));
  await screen.findByText('合成研究回答');
  expect(chatWithAIStream).toHaveBeenCalledTimes(2);
});

it('keeps an ordinary status 404 unknown and never replays the research POST', async () => {
  const selection = { symbol: '600001', market: 'CN', start: '2026-06-17', as_of: '2026-09-15', adjustment: 'stored' };
  const evidence = make(selection);
  localStorage.setItem('mc_research_request_600001', JSON.stringify({ request_id: 'uncertain-404',
    task: { ...selection, question: '普通404仍未知', horizon: 'medium', budget_tokens: 300, max_calls: 1, context_sha256: evidence.context_sha256 },
    evidence, prior_judgments: [], session_id: null }));
  vi.mocked(loadResearchTaskStatus).mockRejectedValue(new Error('404: {"detail":"research_task_not_found"}'));
  render(<EvidenceWorkspace symbol="600001" endDate="2026-09-15" enabled />);
  await waitFor(() => expect(loadResearchTaskStatus).toHaveBeenCalledWith('uncertain-404'), { timeout: 3000 });
  expect(await screen.findByText('远端状态未知', {}, { timeout: 3000 })).toBeInTheDocument();
  expect(chatWithAIStream).not.toHaveBeenCalled();
});

it('stopping the stream only stops local waiting and preserves its request id', async () => {
  vi.mocked(chatWithAIStream).mockImplementationOnce((_payload: any, handlers: any) => new Promise((_resolve, reject) => {
    handlers.signal?.addEventListener('abort', () => {
      const error = new Error('aborted'); error.name = 'AbortError'; reject(error);
    });
  }));
  render(<EvidenceWorkspace symbol="600001" endDate="2026-09-15" enabled />);
  await screen.findByText(/版本 aaaaaaaaaa/);
  fireEvent.change(screen.getByLabelText('本页研究问题'), { target: { value: '停止恢复验证' } });
  fireEvent.click(screen.getByText('准备本次研究'));
  await screen.findByText('准备完成：0 次模型调用');
  fireEvent.click(screen.getByText('开始本次研究'));
  const stop = await screen.findByText('停止本地等待');
  fireEvent.click(stop);
  await screen.findByText(/未发送远端取消请求/);
  const saved = JSON.parse(localStorage.getItem('mc_research_request_600001') || '{}');
  expect(saved.request_id).toEqual(expect.any(String));
  expect(chatWithAIStream).toHaveBeenCalledTimes(1);
});
