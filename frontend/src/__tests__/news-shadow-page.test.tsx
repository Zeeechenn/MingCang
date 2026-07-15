import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { NewsShadowPage } from '../page-news-shadow';
import {
  createNewsShadowFeedback,
  getNewsShadowRun,
  getNewsShadowRuns,
  getNewsShadowSummary,
} from '../services/news-shadow';

vi.mock('../services/news-shadow', () => ({
  getNewsShadowSummary: vi.fn(),
  getNewsShadowRuns: vi.fn(),
  getNewsShadowRun: vi.fn(),
  createNewsShadowFeedback: vi.fn(),
}));

const run = {
  run_id: 'm68:production_mirror:2026-07-15:603986',
  symbol: '603986',
  as_of: '2026-07-15',
  status: 'evidence',
  legacy: { composite_score: 10, recommendation: '观望', signal_date: '2026-07-15' },
  pyramid: { sentiment_score: 80, confidence: 0.82 },
  counterfactual: { composite_score: 38, score_delta: 28, recommendation: '可小仓试错', would_change_action: true, note: 'mechanical same-day sentiment-leg swap only' },
  evidence: { count: 1, content_coverage: 1 },
  event_risk: { level: 'high', reasons: ['new_announcement_event'] },
};

const detail = {
  ...run,
  legacy: {
    ...run.legacy,
    summary: 'latest official signal as-of; counterfactual replaces only the sentiment leg',
  },
  pyramid: {
    ...run.pyramid,
    trigger_reasons: ['new_announcement_event', 'volume_anomaly'],
    attribution: { main_cause: 'company_event', thesis_recheck: true, timeline: [{}] },
    degradation_flags: [],
  },
  price_volume: { price_change_pct: 6.2, volume_ratio: 3 },
  evidence: {
    count: 1,
    content_coverage: 1,
    price_volume: { price_bars_available: 21 },
    items: [{
      evidence_id: 'evidence-1',
      title: '兆易创新签署重要采购合同',
      url: 'https://example.com/news',
      source: '证券时报',
      provider: 'eastmoney',
      published_at: '2026-07-15T09:00:00',
      content_status: 'full',
    }],
  },
  feedback: [],
};

describe('NewsShadowPage', () => {
  beforeEach(() => {
    vi.mocked(getNewsShadowSummary).mockResolvedValue({
      total: 1,
      with_evidence: 1,
      would_change_action: 1,
      price_volume_complete: 1,
      mean_absolute_score_delta: 28,
      tokens_spent_known: 120,
      tokens_unknown_runs: 0,
      event_risk: { high: 1 },
      review_queue: {
        action_divergence: [run.run_id],
        high_importance_untriggered: [],
        stable_control: [],
      },
    });
    vi.mocked(getNewsShadowRuns).mockResolvedValue([run]);
    vi.mocked(getNewsShadowRun).mockResolvedValue(detail);
    vi.mocked(createNewsShadowFeedback).mockResolvedValue({ id: 1 });
  });

  it('surfaces the risk-first judgment and diagnostic evidence', async () => {
    render(<NewsShadowPage />);

    expect(screen.getByText(/情绪更适合解释波动幅度和事件风险/)).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: '兆易创新签署重要采购合同' })).toBeInTheDocument();
    expect(screen.getAllByText('动作分歧').length).toBeGreaterThan(0);
    expect(screen.getByText('公司事件')).toBeInTheDocument();
    expect(screen.getByText(/分歧 1 · 漏触发 0 · 对照 0/)).toBeInTheDocument();
    expect(getNewsShadowRuns).toHaveBeenCalledWith({ asOf: '', symbol: '', onlyDivergent: false, limit: 200 });
  });

  it('writes feedback only through the dedicated shadow endpoint', async () => {
    render(<NewsShadowPage />);
    await screen.findByRole('link', { name: '兆易创新签署重要采购合同' });

    fireEvent.change(screen.getByLabelText('问题类型'), { target: { value: 'wrong_event_class' } });
    fireEvent.change(screen.getByLabelText('关联证据'), { target: { value: 'evidence-1' } });
    fireEvent.change(screen.getByLabelText('反馈说明'), { target: { value: '公告正文归因不充分' } });
    fireEvent.click(screen.getByRole('button', { name: '保存问题样本' }));

    await waitFor(() => expect(createNewsShadowFeedback).toHaveBeenCalledWith(
      run.run_id,
      {
        category: 'wrong_event_class',
        preferred_path: 'unclear',
        evidence_ref: 'evidence-1',
        note: '公告正文归因不充分',
      },
    ));
  });
});
