import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { EvidenceWorkspace } from '../features/research/EvidenceWorkspace';
import { loadResearchContext, loadResearchMessages, loadResearchReviews, saveResearchReview } from '../services/research-context';
import { chatWithAIStream } from '../services/api';

vi.mock('../services/research-context', () => ({ loadResearchContext: vi.fn(), loadResearchReviews: vi.fn(), loadResearchMessages: vi.fn(), saveResearchReview: vi.fn(), saveResearchObservation: vi.fn() }));
vi.mock('../services/api', () => ({ chatWithAIStream: vi.fn() }));
const source = { id: 'price-1', kind: 'price', date: '2026-09-15', source: 'fixture', adjustment: 'qfq', currency: 'CNY', fetched_at: null, values: { close: 11 } };
const make = (selection: any) => ({ selection, context_sha256: selection.as_of === '2026-09-15' ? 'a'.repeat(64) : 'b'.repeat(64), sources: [source], gaps: [], limitations: ['合成测试证据'], can_ask: true });
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear();
  vi.mocked(loadResearchContext).mockImplementation(async s => make(s));
  vi.mocked(loadResearchReviews).mockResolvedValue({ reviews: [] });
  vi.mocked(loadResearchMessages).mockResolvedValue([]);
  vi.mocked(chatWithAIStream).mockImplementation(async (p: any) => ({ answer: '合成研究回答', research_context: p.research_context,
    research_claims: [{ text: '合成研究回答', evidence_ids: ['price-1'] }], session_id: 'page-session' }));
});

it('sends exactly the displayed binding and marks an old answer after date changes', async () => {
  render(<EvidenceWorkspace symbol="600001" endDate="2026-09-15" enabled />);
  await screen.findByText(/版本 aaaaaaaaaa/);
  fireEvent.change(screen.getByLabelText('本页研究问题'), { target: { value: '现金流如何？' } });
  fireEvent.click(screen.getByText('基于这些证据提问'));
  await screen.findByText('合成研究回答');
  expect(vi.mocked(chatWithAIStream).mock.calls[0][0].research_context).toMatchObject({ symbol: '600001', as_of: '2026-09-15', context_sha256: 'a'.repeat(64) });
  fireEvent.change(screen.getByLabelText('证据截止日'), { target: { value: '2026-09-14' } });
  await screen.findByText(/版本 bbbbbbbbbb/);
  expect(screen.getByText(/不适用于当前选择/)).toBeInTheDocument();
  expect(saveResearchReview).not.toHaveBeenCalled();
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
  render(<EvidenceWorkspace symbol="600001" endDate="2026-09-15" enabled />);
  await screen.findByText('财报已过期');
  fireEvent.change(screen.getByLabelText('本页研究问题'), { target: { value: '如何？' } });
  expect(screen.getByText('基于这些证据提问')).toBeDisabled();
  expect(chatWithAIStream).not.toHaveBeenCalled();
});

it('persists a judgment only after explicit submission and keeps evidence', async () => {
  vi.mocked(saveResearchReview).mockImplementation(async (p: any) => ({ review_id: 'record-1', source: make(p.context), result: { version: 1, decision: p, outcomes: [] } }));
  render(<EvidenceWorkspace symbol="600001" endDate="2026-09-15" enabled />);
  await screen.findByText(/版本 aaaaaaaaaa/);
  fireEvent.change(screen.getByLabelText('我的判断'), { target: { value: '等待核实' } });
  fireEvent.change(screen.getByLabelText('判断依据'), { target: { value: '现金流资料不足' } });
  fireEvent.change(screen.getByLabelText('后续验证条件'), { target: { value: '核验下次公告' } });
  expect(saveResearchReview).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('保存判断与证据'));
  await waitFor(() => expect(saveResearchReview).toHaveBeenCalledTimes(1));
  expect(vi.mocked(saveResearchReview).mock.calls[0][0].context.context_sha256).toBe('a'.repeat(64));
  await screen.findByText('验证条件：核验下次公告');
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
  expect(screen.getByText('基于这些证据提问')).toBeDisabled();
  await act(async () => finish([]));
  fireEvent.click(screen.getByText('基于这些证据提问'));
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
  expect(screen.getByText('基于这些证据提问')).toBeDisabled();
  fireEvent.click(screen.getByText('重新载入历史记录'));
  await waitFor(() => expect(screen.getByLabelText('我的判断')).not.toBeDisabled());
  expect(screen.getByText('基于这些证据提问')).not.toBeDisabled();
});
