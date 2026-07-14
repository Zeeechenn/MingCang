import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { HomePage } from '../page-home';
import { MCStore } from '../shared';

describe('HomePage data truth boundary', () => {
  beforeEach(() => {
    MCStore.set({
      live: 'demo',
      liveSources: { watchlist: 'demo' },
      snapshotAsOf: '2026-06-09',
    });
  });

  it('routes connected users to the real research copilot instead of rendering the scripted terminal', () => {
    MCStore.set({ live: 'live', liveSources: { watchlist: 'live' } });
    render(<HomePage />);

    expect(screen.getByRole('status')).toHaveTextContent('数据来源：本地后端 /api');
    expect(screen.getByRole('button', { name: '打开真实研究副驾驶' })).toBeInTheDocument();
    expect(screen.queryByPlaceholderText('输入: 研究 300308 现在还能加仓吗')).not.toBeInTheDocument();
    expect(screen.queryByText('桌面示例通道')).not.toBeInTheDocument();
  });

  it('labels the scripted terminal with its exact demo snapshot date', () => {
    render(<HomePage />);

    expect(screen.getByRole('status')).toHaveTextContent('数据来源：示例快照 · 2026-06-09');
    expect(screen.getByText('示例交互 · 数据截至 2026-06-09')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('输入: 研究 300308 现在还能加仓吗')).toBeInTheDocument();
  });

  it('opens the real copilot from the connected gateway', () => {
    MCStore.set({ live: 'degraded', liveSources: { watchlist: 'live', coverage: 'demo' } });
    render(<HomePage />);

    fireEvent.click(screen.getByRole('button', { name: '打开真实研究副驾驶' }));
    expect(location.hash).toBe('#/chat');
  });
});
