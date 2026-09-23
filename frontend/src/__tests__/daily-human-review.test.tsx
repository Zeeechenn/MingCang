import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { HumanReviewPanel } from '../features/daily/HumanReview';
import { getDailyReviews, saveDailyReview, saveDailyReviewOutcome, type DailyReviews, type HumanReview } from '../services/daily';

vi.mock('../services/daily', () => ({ getDailyReviews: vi.fn(), saveDailyReview: vi.fn(), saveDailyReviewOutcome: vi.fn() }));
const source = { item_id: 'a'.repeat(64), panel_sha256: 'b'.repeat(64), panel_as_of: '2026-09-16', run_id: 'source-run',
  card_type: 'candidate', subject: '600001', name: '测试样本', summary: '等待资料',
  original: { recommendation: '等待资料' }, expires_at: '2026-09-16', validity: 'valid' as const, source_status: 'ready', reviewable: true };
let data: DailyReviews;
function saved(choice = 'accepted'): HumanReview {
  return { review_id: `daily-review:${source.item_id}`, source, can_execute: false,
    result: { version: 1, recorded_at: '2026-09-16T10:00:00Z', actual_execution: 'not_recorded', queue_task_completed: false,
      decision: { choice: choice as 'accepted', rationale: '我已核对', revised_text: choice === 'modified' ? '继续等待' : '' }, outcomes: [] } };
}
beforeEach(() => {
  vi.resetAllMocks();
  data = { panel_as_of: source.panel_as_of, panel_sha256: source.panel_sha256, warning: null,
    items: [{ ...source, review: null }], history: [], history_limit: 100, can_execute: false };
  vi.mocked(getDailyReviews).mockImplementation(async () => data);
  vi.mocked(saveDailyReview).mockImplementation(async request => {
    const review = saved(request.choice); review.result.decision.rationale = request.rationale;
    review.result.decision.revised_text = request.revised_text;
    data = { ...data, items: [{ ...source, review }], history: [review] }; return review;
  });
});

describe('daily human review flow', () => {
  it('loads without writing, preserves original on modification and survives reload', async () => {
    const view = render(<HumanReviewPanel asOf="2026-09-16" />);
    await screen.findByText('等待资料');
    expect(saveDailyReview).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '修改' }));
    expect(screen.getByRole('button', { name: '保存我的选择' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('我的理由'), { target: { value: '我已核对' } });
    fireEvent.change(screen.getByLabelText('修改后的判断'), { target: { value: '继续等待' } });
    fireEvent.click(screen.getByRole('button', { name: '保存我的选择' }));
    await screen.findAllByText('已修改');
    expect(saveDailyReview).toHaveBeenCalledWith({ as_of: source.panel_as_of, item_id: source.item_id,
      panel_sha256: source.panel_sha256, choice: 'modified', rationale: '我已核对', revised_text: '继续等待' });
    expect(data.history[0].source.original).toEqual({ recommendation: '等待资料' });
    view.unmount(); render(<HumanReviewPanel asOf="2026-09-16" />);
    await screen.findAllByText('修改后的判断：继续等待');
    expect(screen.queryByRole('button', { name: '接受' })).not.toBeInTheDocument();
  });

  it('does not present success when a write fails and preserves entered reasons', async () => {
    vi.mocked(saveDailyReview).mockRejectedValue(new Error('409 panel_changed_reload_required'));
    render(<HumanReviewPanel asOf="2026-09-16" />);
    fireEvent.click(await screen.findByRole('button', { name: '接受' }));
    fireEvent.change(screen.getByLabelText('我的理由'), { target: { value: '待核对的理由' } });
    fireEvent.click(screen.getByRole('button', { name: '保存我的选择' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('证据已变化');
    expect(screen.getByLabelText('我的理由')).toHaveValue('待核对的理由');
    expect(screen.queryByText('已接受')).not.toBeInTheDocument();
    expect(saveDailyReview).toHaveBeenCalledTimes(1);
  });

  it('allows rejection but blocks acceptance for expired evidence', async () => {
    data.items[0].validity = 'expired';
    render(<HumanReviewPanel asOf="2026-09-16" />);
    expect(await screen.findByRole('button', { name: '接受' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '修改' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '拒绝' })).toBeEnabled();
  });

  it('appends an observation with the loaded version and preserves the decision', async () => {
    const review = saved(); data.items[0].review = review; data.history = [review];
    vi.mocked(saveDailyReviewOutcome).mockImplementation(async (_id, value) => {
      const updated = { ...review, result: { ...review.result, version: 2,
        outcomes: [{ ...value, recorded_at: '2026-09-17T10:00:00Z', source: 'human_reported_not_independently_verified' }] } };
      return updated;
    });
    render(<HumanReviewPanel asOf="2026-09-16" />);
    await screen.findAllByText('已接受');
    const item = screen.getByRole('article', { name: '候选研究 测试样本' });
    fireEvent.click(within(item).getByRole('button', { name: '记录后续观察' }));
    fireEvent.change(screen.getByLabelText('观察说明'), { target: { value: '仍需更新公告' } });
    fireEvent.click(screen.getByRole('button', { name: '保存后续观察' }));
    await waitFor(() => expect(saveDailyReviewOutcome).toHaveBeenCalledWith(review.review_id, expect.objectContaining({ expected_version: 1, status: 'inconclusive', note: '仍需更新公告' })));
    await screen.findAllByText(/仍需更新公告/);
    expect(screen.queryByLabelText('观察说明')).not.toBeInTheDocument();
  });
});

it('keeps dated backlog available without presenting it as current material', async () => {
  data.items.push({ ...source, item_id: 'c'.repeat(64), name: '旧事项', subject: '600002',
    card_type: 'human_confirmation', summary: '七月遗留研究', source_scope: 'historical', source_date: '2026-07-05', review: null });
  data.items.push({ ...source, item_id: 'd'.repeat(64), name: '未标日期', subject: '600003',
    card_type: 'human_confirmation', summary: '日期未知研究', source_scope: 'unverified', source_date: null, review: null });
  data.summary = { current: 1, historical: 1, unverified: 1, recorded_choices: 0, with_observations: 0, independently_verified_outcomes: null };
  render(<HumanReviewPanel asOf="2026-09-16" />);
  await screen.findByText('等待资料');
  expect(screen.queryByText('七月遗留研究')).not.toBeInTheDocument();
  expect(screen.queryByText('日期未知研究')).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('资料范围'), { target: { value: 'historical' } });
  expect(screen.getByText('七月遗留研究')).toBeInTheDocument();
  expect(screen.getByText(/历史事项，创建于 2026-07-05/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('资料范围'), { target: { value: 'unverified' } });
  expect(screen.getByText('日期未知研究')).toBeInTheDocument();
  expect(saveDailyReview).not.toHaveBeenCalled();
});
