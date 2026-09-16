import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DailyPage } from '../page-daily';

const cards = [
  'batch_integrity',
  'candidate',
  'position_health',
  'event_risk',
  'watchtower',
  'daily_delta',
  'human_confirmation',
  'review_attribution',
].map((card_type) => ({
  card_type,
  lifecycle: card_type === 'event_risk' || card_type === 'watchtower' ? 'shadow' : 'stable',
  status: card_type === 'daily_delta' ? 'missing' : 'ready',
  summary: `${card_type} summary`,
  payload: card_type === 'event_risk'
    ? { notification_contract: { would_suppress: false }, suppression_history_status: 'missing', direction_weights: { lifecycle: 'shadow', status: 'blocked' }, panel_payload: { attention_count: 1 } }
    : card_type === 'candidate'
      ? { shadow_discretion_cards: [], stale_discretion_count: 0, count: 1 }
      : { count: 1 },
  evidence_refs: [{ source_type: 'test', source_ref: card_type, status: 'ready' }],
  run_ref: { run_id: 'run-1', batch_id: 'batch-1', status: 'complete' },
  drilldown: {
    kind: 'route',
    href: card_type === 'event_risk' ? '/news-shadow' : '/daily',
    label: card_type === 'event_risk' ? '查看新闻试用' : '查看',
  },
}));

vi.mock('../services/daily', () => ({
  getDailyReviews: vi.fn(() => Promise.resolve({ items: [], history: [], history_limit: 100 })),
  getDailyPanelLatest: vi.fn(() => Promise.resolve({
    schema_version: 'daily_panel.v1',
    mode: 'postmarket',
    as_of: '2026-08-18',
    generated_at: '2026-08-18T16:00:00Z',
    status: 'ready',
    cards,
    lifecycle_visibility: {
      stable: ['batch_integrity', 'candidate', 'position_health', 'daily_delta', 'human_confirmation', 'review_attribution'],
      shadow: ['event_risk', 'watchtower'],
      dormant: [],
      rejected: [],
    },
    source_contract: { read_only: true, no_synthetic_batch: true },
  })),
}));

vi.mock('../services/api', () => ({
  getLatestM63Report: vi.fn(() => Promise.reject({ status: 404 })),
}));

describe('DailyPage Stage5 panel', () => {
  it('renders the canonical 8-card daily panel with lifecycle tabs and drilldown', async () => {
    render(<DailyPage />);

    await screen.findByText('daily_panel.v1 · postmarket');
    for (const card of cards) {
      expect(screen.getByText(card.card_type)).toBeInTheDocument();
      expect(screen.getByText(`${card.card_type} summary`)).toBeInTheDocument();
    }
    expect(screen.getAllByText(/Run run-1/).length).toBeGreaterThan(0);
    expect(screen.getByRole('tab', { name: 'Shadow' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /新闻\/事件风险 drilldown 查看新闻试用/ }));
    expect(window.location.hash).toBe('#/news-shadow');
  });

  it('filters degraded or missing cards without hiding the shell', async () => {
    render(<DailyPage />);

    await screen.findByText('daily_panel.v1 · postmarket');
    fireEvent.click(screen.getByRole('tab', { name: 'Missing / Blocked' }));
    expect(screen.getByText('daily_delta')).toBeInTheDocument();
    expect(screen.queryByText('candidate')).not.toBeInTheDocument();
  });

  it('wraps long payload labels inside mini-cards for mobile widths', async () => {
    const { container } = render(<DailyPage />);

    await screen.findByText('daily_panel.v1 · postmarket');
    const longLabel = container.querySelector('[data-payload-key="shadow_discretion_cards"]') as HTMLElement;
    expect(longLabel).toBeTruthy();
    expect(longLabel.style.overflowWrap).toBe('anywhere');
    expect(longLabel.style.wordBreak).toBe('break-word');
    expect(longLabel.style.whiteSpace).toBe('normal');
  });

  it('initializes the lifecycle tab from the daily hash query', async () => {
    window.location.hash = '#/daily?tab=shadow';
    render(<DailyPage />);

    await screen.findByText('daily_panel.v1 · postmarket');
    expect(screen.getByRole('tab', { name: 'Shadow' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('event_risk')).toBeInTheDocument();
    expect(screen.queryByText('candidate')).not.toBeInTheDocument();
    window.location.hash = '';
  });
});

it('shows explicit zero and disabled reasons without hiding missing evidence', async () => {
  const { DailyCard } = await import('../features/daily/DailyPanel');
  render(<DailyCard card={{...cards[3], status: 'not_applicable',
    payload: { reason: '本次关闭新闻影子分析；不能解释为没有事件风险。' }}} />);
  expect(screen.getByText('本次未启用')).toBeInTheDocument();
  expect(screen.getByText('本次关闭新闻影子分析；不能解释为没有事件风险。')).toBeInTheDocument();
  render(<DailyCard card={{...cards[5], status: 'ready_zero', payload: {
    reason: '候选名单核对完成，无新增。', structured_delta: {
      current_as_of: '2026-09-16', previous_as_of: '2026-09-15', candidate_added: [], candidate_removed: [],
    }}}} />);
  expect(screen.getByText('已核对 · 无新增')).toBeInTheDocument();
  expect(screen.getByText('当前 2026-09-16 · 对比 2026-09-15')).toBeInTheDocument();
});
