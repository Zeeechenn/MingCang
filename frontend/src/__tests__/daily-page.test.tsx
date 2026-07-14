import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DailyPage } from '../page-daily';

vi.mock('../services/api', () => ({
  getLatestM59Discretion: vi.fn(() => Promise.resolve([])),
  getLatestM63Report: vi.fn(() => Promise.reject({ status: 404 })),
  getM63Queue: vi.fn(() => Promise.resolve({ pending: [], done: [] })),
}));

describe('DailyPage workflow boundary', () => {
  it('describes the four report lanes and routes research actions to the real copilot', async () => {
    render(<DailyPage />);

    await screen.findByText('暂无该时段报告');
    expect(screen.getByText(/四类报告/)).toBeInTheDocument();
    expect(screen.queryByText(/六个工作流入口/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '研究目标' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '记录观点' })).toBeInTheDocument();
  });
});
